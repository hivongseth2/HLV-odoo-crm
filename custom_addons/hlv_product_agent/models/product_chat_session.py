# -*- coding: utf-8 -*-
"""Một cuộc hội thoại của một sale với trợ lý tạo mã hàng.

Vòng đời một lượt:
    sale gửi tin (to_send=True) -> agent poll, claim_jobs() cầm tin bằng claim_token
    -> agent chạy Claude, tool MISA đi qua Odoo kèm claim_token -> deliver_reply().
"""
import base64
import binascii
import logging
import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services import build_turn_prompt, parse_sale_identities

_logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 4000
MAX_IMAGES_PER_MESSAGE = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Agent cho mỗi lần chạy Claude tối đa 5 phút và có thể chạy lại một lần khi mất
# phiên; quá ngưỡng này mà chưa trả lời thì chắc chắn agent đã chết giữa chừng.
CLAIM_TIMEOUT_MINUTES = 12
# Số tin cũ gửi kèm khi Claude mất phiên và phải dựng lại ngữ cảnh.
COLD_START_HISTORY_LIMIT = 12
MANAGER_GROUP = 'hlv_product_agent.group_product_agent_manager'


class HlvProductChatSession(models.Model):
    _name = 'hlv.product.chat.session'
    _description = "Hội thoại trợ lý tạo mã hàng"
    _order = 'last_activity desc, id desc'

    name = fields.Char("Chủ đề", default="Hội thoại mới", required=True)
    user_id = fields.Many2one(
        'res.users', string="Tài khoản", required=True, index=True,
        default=lambda self: self.env.user,
    )
    # Nhiều sale dùng chung một tài khoản Odoo: cuộc chat phải tách theo NGƯỜI, không
    # thì tin của hai người lẫn vào một phiên Claude — người này "OK" là tạo hàng của
    # người kia. Tài khoản một người thì sale_key rỗng.
    sale_key = fields.Char("Mã người chat", index=True, readonly=True)
    sale_name = fields.Char("Nhân viên", readonly=True)
    sale_code = fields.Char("Mã sale MISA", readonly=True)
    closed = fields.Boolean(
        "Đã kết thúc", default=False,
        help="Sale bấm 'Cuộc mới' thì cuộc cũ kết thúc; Claude bắt đầu phiên mới không nhớ cuộc cũ.",
    )
    last_activity = fields.Datetime("Hoạt động cuối", default=fields.Datetime.now)
    state = fields.Selection(
        [('idle', "Chờ tin"), ('processing', "Claude đang xử lý")],
        default='idle', required=True, readonly=True,
    )
    claim_token = fields.Char(readonly=True, copy=False, index=True)
    claim_date = fields.Datetime(readonly=True, copy=False)
    claude_session_id = fields.Char(
        "Mã phiên Claude", readonly=True, copy=False,
        help="Agent dùng mã này để --resume, nhờ vậy lượt sau chỉ cần gửi tin mới.",
    )
    message_ids = fields.One2many('hlv.product.chat.message', 'session_id', string="Tin nhắn")

    # =========================================================================
    # PHÍA SALE (khung chat)
    # =========================================================================
    @api.model
    def sale_identities(self, user):
        """Danh sách sale dùng tài khoản này, xem services.sale_identity.

        Hai field do module khác khai (misa_invoice_status_report,
        hlv_sale_delivery_planning); tài khoản không khai gì -> [].
        """
        user = user.sudo()
        return parse_sale_identities(user.x_misa_saler_codes, user.x_sale_plan_mention_names)

    @api.model
    def current_for_user(self, identity=None):
        """Cuộc đang mở của tài khoản hiện tại, đúng người đang chat. Rỗng nếu chưa có."""
        return self.search([
            ('user_id', '=', self.env.uid),
            ('sale_key', '=', self._key_of(identity)),
            ('closed', '=', False),
        ], limit=1)

    @api.model
    def create_for_user(self, identity=None):
        return self.create({
            'user_id': self.env.uid,
            'sale_key': self._key_of(identity),
            'sale_name': identity['name'] if identity else self.env.user.name,
            'sale_code': identity['code'] if identity else False,
        })

    @api.model
    def start_new_for_user(self, identity=None):
        """Kết thúc cuộc đang mở của đúng người này (nếu có) và mở cuộc mới."""
        current = self.current_for_user(identity)
        if current:
            current.sudo().closed = True
        return self.create_for_user(identity)

    @staticmethod
    def _key_of(identity):
        # Tài khoản 1 người: key rỗng, khớp cả các cuộc tạo trước khi có tách người.
        return (identity or {}).get('key') or False

    def post_user_message(self, text, images=None):
        """Ghi tin sale gửi vào hàng chờ.

        Nhận: text, images = list dict ``{'name', 'mimetype', 'data' (base64)}``.
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
        checked_images = [self._check_image(image) for image in images]

        message = self.env['hlv.product.chat.message'].sudo().create({
            'session_id': self.id,
            'role': 'user',
            'content': text or False,
            'to_send': True,
        })
        if checked_images:
            attachments = self.env['ir.attachment'].sudo().create([
                dict(image, res_model=message._name, res_id=message.id)
                for image in checked_images
            ])
            message.attachment_ids = [(6, 0, attachments.ids)]

        vals = {'last_activity': fields.Datetime.now()}
        if self.name == "Hội thoại mới" and text:
            vals['name'] = text[:60]
        self.sudo().write(vals)
        return message

    @staticmethod
    def _check_image(image):
        """Kiểm một ảnh sale gửi lên. Trả vals cho ir.attachment, raise UserError nếu hỏng."""
        mimetype = (image.get('mimetype') or '').lower()
        if not mimetype.startswith('image/'):
            raise UserError(_("Chỉ nhận file ảnh."))
        try:
            raw = base64.b64decode(image.get('data') or '', validate=True)
        except (binascii.Error, ValueError):
            raise UserError(_("Ảnh gửi lên bị hỏng."))
        if not raw:
            raise UserError(_("Ảnh gửi lên bị rỗng."))
        if len(raw) > MAX_IMAGE_BYTES:
            raise UserError(_("Ảnh quá lớn (tối đa %s MB).") % (MAX_IMAGE_BYTES // 1024 // 1024))
        return {
            'name': (image.get('name') or 'anh.jpg')[:120],
            'mimetype': mimetype,
            'datas': base64.b64encode(raw),
        }

    def client_state(self, after_id=0):
        """Trạng thái cho khung chat: tin mới hơn after_id, đang bận hay không."""
        self.ensure_one()
        messages = self.message_ids.filtered(lambda m: m.id > (after_id or 0))
        waiting = self.state == 'idle' and any(self.message_ids.mapped('to_send'))
        return {
            'session_id': self.id,
            'busy': self.state == 'processing' or waiting,
            'processing': self.state == 'processing',
            # Số cuộc đang chờ trước mình; None khi mình không chờ. Agent chạy song
            # song vài cuộc nên số này là "tối đa phải chờ", không phải thứ tự chính xác.
            'queue_ahead': self._queue_ahead() if waiting else None,
            'messages': [msg.to_client_dict() for msg in messages],
        }

    def _queue_ahead(self):
        """Số cuộc có tin chờ gửi TRƯỚC cuộc này (cùng quy tắc xếp hàng với claim_jobs)."""
        self.ensure_one()
        self.env.cr.execute("""
            WITH waiting AS (
                SELECT s.id, MIN(m.id) AS first_pending
                  FROM hlv_product_chat_session s
                  JOIN hlv_product_chat_message m ON m.session_id = s.id AND m.to_send
                 WHERE s.state = 'idle'
                 GROUP BY s.id
            )
            SELECT COUNT(*) FROM waiting
             WHERE first_pending < (SELECT first_pending FROM waiting WHERE id = %s)
        """, [self.id])
        return self.env.cr.fetchone()[0] or 0

    # =========================================================================
    # PHÍA AGENT
    # =========================================================================
    @api.model
    def claim_jobs(self, limit):
        """Cầm tối đa `limit` cuộc hội thoại đang có tin chờ, trả list job cho agent.

        SKIP LOCKED để hai agent (hoặc hai lần poll chồng nhau) không bao giờ cầm
        trùng một cuộc — cầm trùng là Claude chạy hai lần, có thể tạo mã hai lần.

        Xếp theo tin chờ CŨ NHẤT của mỗi cuộc (ai gửi trước được làm trước), không theo
        last_activity: người gửi liền nhiều tin sẽ bị đẩy lùi mãi nếu xếp theo lần cuối.
        """
        self.env.cr.execute("""
            SELECT s.id FROM hlv_product_chat_session s
             WHERE s.state = 'idle'
               AND EXISTS (SELECT 1 FROM hlv_product_chat_message m
                            WHERE m.session_id = s.id AND m.to_send)
             ORDER BY (SELECT MIN(m.id) FROM hlv_product_chat_message m
                        WHERE m.session_id = s.id AND m.to_send)
             LIMIT %s
             FOR UPDATE OF s SKIP LOCKED
        """, [max(int(limit or 1), 1)])
        session_ids = [row[0] for row in self.env.cr.fetchall()]
        return [session._claim() for session in self.sudo().browse(session_ids)]

    def _claim(self):
        self.ensure_one()
        pending = self.message_ids.filtered(lambda m: m.to_send and m.role == 'user')
        token = uuid.uuid4().hex
        pending.write({'claim_token': token})
        self.write({'state': 'processing', 'claim_token': token, 'claim_date': fields.Datetime.now()})

        is_admin = self.user_id.has_group(MANAGER_GROUP)
        new_items = [msg.to_prompt_dict() for msg in pending]
        history = self.message_ids.filtered(
            lambda m: m.id < pending[:1].id and m.role in ('user', 'assistant')
        )[-COLD_START_HISTORY_LIMIT:]
        prompt = build_turn_prompt(new_items, is_admin)
        return {
            'claim_token': token,
            'session_id': self.id,
            'claude_session_id': self.claude_session_id or '',
            'prompt': prompt,
            # Chỉ dùng khi agent không resume được phiên Claude cũ.
            'prompt_cold': build_turn_prompt(
                new_items, is_admin, [msg.to_prompt_dict() for msg in history],
            ) if history else prompt,
            'attachments': [
                {'id': att.id, 'filename': name}
                for msg, item in zip(pending, new_items)
                for att, name in zip(msg.attachment_ids, item['attachments'])
            ],
        }

    @api.model
    def from_claim(self, claim_token):
        """Cuộc hội thoại đang được xử lý dưới claim_token này. Rỗng nếu lượt đã đóng."""
        if not claim_token or not isinstance(claim_token, str):
            return self.browse()
        return self.sudo().search([
            ('state', '=', 'processing'), ('claim_token', '=', claim_token),
        ], limit=1)

    def deliver_reply(self, reply, claude_session_id=None, error=None):
        """Chốt một lượt: lưu câu trả lời (hoặc lỗi) và thả cuộc hội thoại về 'Chờ tin'."""
        self.ensure_one()
        claimed = self.message_ids.filtered(lambda m: m.claim_token == self.claim_token)
        claimed.write({'to_send': False})
        reply = (reply or '').strip()
        if reply:
            self._post('assistant', reply)
        if error or not reply:
            _logger.warning("PRODUCT_AGENT phiên %s lỗi: %s", self.id, error)
            self._post('event', _(
                "Máy trợ lý gặp lỗi nên chưa trả lời được (%s). Anh/chị gửi lại tin giúp em."
            ) % (error or _("không có câu trả lời"))[:300])

        vals = {'state': 'idle', 'claim_token': False, 'claim_date': False,
                'last_activity': fields.Datetime.now()}
        if claude_session_id:
            vals['claude_session_id'] = claude_session_id[:64]
        self.write(vals)

    @api.model
    def release_stale(self):
        """Thả các lượt agent cầm quá lâu mà không trả lời (agent chết giữa chừng).

        Không tự chạy lại: tool MISA có thể đã tạo mã trước khi agent chết, chạy lại là
        tạo trùng. Báo sale gửi lại để Claude quét trùng từ đầu.
        """
        threshold = fields.Datetime.now() - timedelta(minutes=CLAIM_TIMEOUT_MINUTES)
        stale = self.sudo().search([('state', '=', 'processing'), ('claim_date', '<', threshold)])
        for session in stale:
            session.deliver_reply('', error=_("quá thời gian chờ"))
        return stale

    def previous_reply(self):
        """Câu trả lời gần nhất của trợ lý TRƯỚC lượt đang xử lý — thứ sale đã thấy.

        Tính từ tin đầu tiên của lượt hiện tại (claim_token), không phải từ cuối cuộc:
        câu trả lời của chính lượt này chưa được lưu, và nếu có lưu thì sale cũng chưa
        kịp đọc. Trả chuỗi rỗng nếu chưa có câu trả lời nào.
        """
        self.ensure_one()
        claimed = self.message_ids.filtered(
            lambda m: self.claim_token and m.claim_token == self.claim_token)
        before = claimed[:1].id or float('inf')
        replies = self.message_ids.filtered(lambda m: m.role == 'assistant' and m.id < before)
        return replies[-1:].content or ''

    def post_event(self, text):
        """Ghi chú hệ thống (đã tạo/sửa MISA...) — sale thấy, Claude không nhận."""
        self.ensure_one()
        return self._post('event', text)

    def _post(self, role, text):
        return self.env['hlv.product.chat.message'].sudo().create({
            'session_id': self.id, 'role': role, 'content': text,
        })
