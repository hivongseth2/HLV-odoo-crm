# -*- coding: utf-8 -*-
"""Một cuộc chat của quản trị với trợ lý.

Vòng đời một lượt:
    gửi tin (to_send=True) -> runner cầm cuộc bằng claim_token -> Claude chạy, tool chạy dưới
    claim_token đó -> deliver_reply() thả cuộc về 'Chờ tin'.

Khác trợ lý tạo mã: không có tài khoản dùng chung nhiều người, không có máy văn phòng — mỗi cuộc
thuộc đúng một tài khoản, mở lại và chat tiếp cuộc cũ lúc nào cũng được (như Claude desktop).
"""
import json
import logging
import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.hlv_product_agent.models.product_chat_session import (
    COLD_START_HISTORY_LIMIT, MAX_IMAGES_PER_MESSAGE, MAX_TEXT_CHARS,
)
from odoo.addons.hlv_product_agent.services import build_turn_prompt
from odoo.addons.hlv_product_agent.services.claude_api_payload import INLINE_IMAGE_NOTE, MODEL_CHOICES

_logger = logging.getLogger(__name__)

NEW_SESSION_NAME = "Cuộc chat mới"
SIDEBAR_LIMIT = 60
# Lượt API tự dừng ở TURN_DEADLINE_SECONDS (6 phút); quá ngưỡng này mà chưa trả lời thì chắc
# chắn luồng chạy đã chết giữa chừng.
CLAIM_TIMEOUT_MINUTES = 12


class HlvAdminChatSession(models.Model):
    _name = 'hlv.admin.chat.session'
    _description = "Cuộc chat trợ lý quản trị"
    _order = 'last_activity desc, id desc'

    name = fields.Char("Chủ đề", default=NEW_SESSION_NAME, required=True)
    user_id = fields.Many2one('res.users', string="Tài khoản", required=True, index=True,
                              default=lambda self: self.env.user)
    # Người dùng chọn trên trang chat; trống = model trong Cấu hình. Đổi giữa cuộc là lượt sau mở lại
    # lịch sử từ tin chữ (khối thinking gắn với model cũ, API không nhận).
    model = fields.Selection(MODEL_CHOICES, string="Model")
    last_activity = fields.Datetime("Hoạt động cuối", default=fields.Datetime.now)
    state = fields.Selection([('idle', "Chờ tin"), ('processing', "Claude đang xử lý")],
                             default='idle', required=True, readonly=True)
    claim_token = fields.Char(readonly=True, copy=False, index=True)
    claim_date = fields.Datetime(readonly=True, copy=False)
    message_ids = fields.One2many('hlv.admin.chat.message', 'session_id', string="Tin nhắn")
    # Lịch sử gửi Claude API (JSON list), chỉ NỐI THÊM — sửa phần cũ là API từ chối khối thinking.
    api_messages = fields.Text(readonly=True, copy=False)
    api_context_key = fields.Char(readonly=True, copy=False)
    api_history_date = fields.Datetime("Lượt API gần nhất", readonly=True, copy=False)
    # Tên field trùng hlv.product.chat.session: model phụ tra cứu của trợ lý tạo mã ghi token
    # thẳng vào cuộc chat qua _record_usage.
    api_input_tokens = fields.Integer("Token vào", readonly=True, copy=False)
    api_cache_read_tokens = fields.Integer("Token đọc cache", readonly=True, copy=False)
    api_output_tokens = fields.Integer("Token ra", readonly=True, copy=False)
    api_last_prompt_tokens = fields.Integer("Độ dài prompt gần nhất", readonly=True, copy=False)

    # =========================================================================
    # PHÍA TRANG CHAT (đã kiểm quyền ở controller; chỉ đụng cuộc của chính mình)
    # =========================================================================
    @api.model
    def sidebar_for_user(self):
        """Các cuộc chat của tài khoản đang đăng nhập, mới nhất trước — cột trái của trang."""
        sessions = self.search([('user_id', '=', self.env.uid)], limit=SIDEBAR_LIMIT)
        return [{
            'id': session.id,
            'name': session.name,
            'date': fields.Datetime.to_string(session.last_activity),
            'busy': session.state == 'processing' or any(session.message_ids.mapped('to_send')),
        } for session in sessions]

    @api.model
    def owned(self, session_id):
        """Cuộc chat session_id nếu thuộc tài khoản đang đăng nhập; rỗng nếu không."""
        try:
            session_id = int(session_id or 0)
        except (TypeError, ValueError):
            return self.browse()
        return self.search([('id', '=', session_id), ('user_id', '=', self.env.uid)], limit=1)

    def set_model(self, model):
        """Đổi model của cuộc. Model không có trong danh sách thì bỏ qua (giữ model cũ). Trả True nếu đổi."""
        self.ensure_one()
        if model not in dict(MODEL_CHOICES) or model == self.model:
            return False
        self.sudo().model = model
        return True

    def post_user_message(self, text, images=None):
        """Ghi tin người dùng vào hàng chờ và đánh thức runner.

        Nhận: text, images = list ``{'name', 'mimetype', 'data' (base64)}``.
        Raise UserError khi tin rỗng, quá dài, hoặc ảnh không hợp lệ.
        """
        self.ensure_one()
        text = (text or '').strip()
        images = images or []
        if not text and not images:
            raise UserError(_("Chưa nhập nội dung."))
        if len(text) > MAX_TEXT_CHARS:
            raise UserError(_("Tin nhắn quá dài (tối đa %s ký tự).") % MAX_TEXT_CHARS)
        if len(images) > MAX_IMAGES_PER_MESSAGE:
            raise UserError(_("Mỗi tin gửi tối đa %s ảnh.") % MAX_IMAGES_PER_MESSAGE)
        # Cùng luật kiểm ảnh với khung chat của sale.
        checked = [self.env['hlv.product.chat.session']._check_image(image) for image in images]

        message = self.env['hlv.admin.chat.message'].sudo().create({
            'session_id': self.id, 'role': 'user', 'content': text or False, 'to_send': True,
        })
        if checked:
            attachments = self.env['ir.attachment'].sudo().create([
                dict(image, res_model=message._name, res_id=message.id) for image in checked])
            message.attachment_ids = [(6, 0, attachments.ids)]

        vals = {'last_activity': fields.Datetime.now()}
        if self.name == NEW_SESSION_NAME and text:
            vals['name'] = text[:60]
        self.sudo().write(vals)
        self.env['hlv.admin.agent.runner'].wake(self.id)
        return message

    def client_state(self, after_id=0):
        """Trạng thái cho trang chat: tin mới hơn after_id, đang bận hay không."""
        self.ensure_one()
        return {
            'session_id': self.id,
            'name': self.name,
            'model': self.model or False,
            'busy': self.state == 'processing' or any(self.message_ids.mapped('to_send')),
            'processing': self.state == 'processing',
            'messages': [msg.to_client_dict() for msg in self.message_ids if msg.id > (after_id or 0)],
        }

    # =========================================================================
    # PHÍA RUNNER
    # =========================================================================
    def claim(self):
        """Cầm cuộc này nếu đang rảnh và có tin chờ. Trả claim_token, hoặc '' nếu không cầm được.

        FOR UPDATE SKIP LOCKED: hai luồng (gửi liền hai tin, cron vớt tin) không bao giờ cầm trùng
        — cầm trùng là Claude chạy hai lần, có thể tạo báo giá hai lần.
        """
        self.ensure_one()
        self.env.cr.execute("""
            SELECT s.id FROM hlv_admin_chat_session s
             WHERE s.id = %s AND s.state = 'idle'
               AND EXISTS (SELECT 1 FROM hlv_admin_chat_message m WHERE m.session_id = s.id AND m.to_send)
               FOR UPDATE SKIP LOCKED
        """, [self.id])
        if not self.env.cr.fetchone():
            return ''
        token = uuid.uuid4().hex
        self.message_ids.filtered(lambda m: m.to_send and m.role == 'user').write({'claim_token': token})
        self.write({'state': 'processing', 'claim_token': token, 'claim_date': fields.Datetime.now()})
        return token

    @api.model
    def from_claim(self, claim_token):
        """Cuộc đang được xử lý dưới claim_token này. Rỗng nếu lượt đã đóng."""
        if not claim_token or not isinstance(claim_token, str):
            return self.browse()
        return self.sudo().search([('state', '=', 'processing'), ('claim_token', '=', claim_token)], limit=1)

    def api_turn_input(self):
        """Đầu vào lượt đang cầm: ``{'prompt', 'prompt_cold', 'images'}``.

        prompt_cold kèm các tin gần nhất, dùng khi không còn lịch sử API (đổi prompt, nghỉ lâu).
        Mọi tin mang marker quyền quản lý: phụ lục trợ lý tạo mã đọc marker này.
        """
        self.ensure_one()
        claimed = self.message_ids.filtered(
            lambda m: self.claim_token and m.claim_token == self.claim_token and m.role == 'user')
        items = [msg.to_prompt_dict() for msg in claimed]
        history = self.message_ids.filtered(
            lambda m: m.id < claimed[:1].id and m.role in ('user', 'assistant'))[-COLD_START_HISTORY_LIMIT:]
        prompt = build_turn_prompt(items, True, image_note=INLINE_IMAGE_NOTE)
        prompt_cold = build_turn_prompt(
            items, True, [msg.to_prompt_dict() for msg in history], image_note=INLINE_IMAGE_NOTE,
        ) if history else prompt
        images = [image for msg in claimed for image in msg.api_image_payloads()]
        return {'prompt': prompt, 'prompt_cold': prompt_cold, 'images': images}

    def deliver_reply(self, reply, error=None):
        """Chốt một lượt: lưu câu trả lời (hoặc lỗi) và thả cuộc về 'Chờ tin'."""
        self.ensure_one()
        self.message_ids.filtered(lambda m: m.claim_token == self.claim_token).write({'to_send': False})
        reply = (reply or '').strip()
        if reply:
            self._post('assistant', reply)
        if error or not reply:
            _logger.warning("ADMIN_AGENT cuộc %s lỗi: %s", self.id, error)
            self._post('event', _("Trợ lý gặp lỗi nên chưa trả lời được (%s). Gửi lại tin giúp em.")
                       % (error or _("không có câu trả lời"))[:300])
        self.write({'state': 'idle', 'claim_token': False, 'claim_date': False,
                    'last_activity': fields.Datetime.now()})

    @api.model
    def release_stale(self):
        """Thả các lượt cầm quá lâu mà không trả lời. Không tự chạy lại: lệnh ghi có thể đã xong."""
        threshold = fields.Datetime.now() - timedelta(minutes=CLAIM_TIMEOUT_MINUTES)
        stale = self.sudo().search([('state', '=', 'processing'), ('claim_date', '<', threshold)])
        for session in stale:
            session.deliver_reply('', error=_("quá thời gian chờ"))
        return stale

    def previous_reply(self):
        """Câu trả lời gần nhất của trợ lý TRƯỚC lượt đang xử lý — thứ người dùng đã thấy.

        Căn cứ của chốt "đề xuất trước, ghi sau". Trả '' nếu chưa có câu trả lời nào.
        """
        self.ensure_one()
        claimed = self.message_ids.filtered(lambda m: self.claim_token and m.claim_token == self.claim_token)
        before = claimed[:1].id or float('inf')
        replies = self.message_ids.filtered(lambda m: m.role == 'assistant' and m.id < before)
        return replies[-1:].content or ''

    def post_event(self, text):
        """Ghi chú hệ thống (đã tạo báo giá...) — người dùng thấy, Claude không nhận."""
        self.ensure_one()
        return self._post('event', text)

    def post_client_action(self, text, action):
        """Ghi chú hệ thống kèm lệnh cho trang (dict, vd ``{'type': 'panel', 'title', 'html'}``)."""
        self.ensure_one()
        message = self._post('event', text)
        message.client_action = json.dumps(action, ensure_ascii=False)
        return message

    def _post(self, role, text):
        return self.env['hlv.admin.chat.message'].sudo().create({
            'session_id': self.id, 'role': role, 'content': text,
        })
