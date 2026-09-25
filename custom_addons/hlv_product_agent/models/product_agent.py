# -*- coding: utf-8 -*-
"""Máy chạy Claude: một bản ghi, một token."""
import secrets
from datetime import timedelta

from odoo import api, fields, models

from ..services import ENROLL_CODE_LENGTH, normalize_enroll_code, random_enroll_code

# Mã cài đặt chỉ sống đủ lâu để người ta đi từ form Odoo tới máy cài agent.
ENROLL_CODE_TTL_MINUTES = 30

# Agent poll vài giây một lần. Im lâu hơn ngưỡng này thì coi như máy tắt — để rộng
# gấp nhiều lần chu kỳ poll vì mạng chớp là chuyện thường.
AGENT_ALIVE_WINDOW_SECONDS = 60


class HlvProductAgent(models.Model):
    _name = 'hlv.product.agent'
    _description = "Máy chạy trợ lý tạo mã hàng"

    name = fields.Char("Tên máy", required=True, default="Máy văn phòng")
    active = fields.Boolean(default=True)
    # Chỉ admin hệ thống thấy: token là thứ duy nhất chặn người lạ gọi tool MISA.
    token = fields.Char(
        "Token agent", required=True, copy=False, groups='base.group_system',
        default=lambda self: secrets.token_urlsafe(32),
        help="Dán vào agent.yaml trên máy chạy Claude. Sinh lại là agent cũ mất quyền ngay.",
    )
    last_seen = fields.Datetime("Gọi lần cuối", readonly=True)
    version = fields.Char("Phiên bản agent", readonly=True)
    enroll_code = fields.Char(
        "Mã cài đặt", copy=False, readonly=True, groups='base.group_system',
        help="Mã dùng một lần để script cài đặt tự lấy token. Hết hạn sau %d phút."
             % ENROLL_CODE_TTL_MINUTES,
    )
    enroll_code_expiry = fields.Datetime(readonly=True, copy=False, groups='base.group_system')
    setup_command = fields.Char(compute='_compute_setup_command')
    agent_status = fields.Selection(
        [('never', "Chưa bao giờ gọi"), ('alive', "Đang chạy"), ('dead', "Đã ngừng")],
        string="Tình trạng", compute='_compute_agent_status',
    )

    @api.depends('last_seen')
    def _compute_agent_status(self):
        # Non-stored: kết quả phụ thuộc thời điểm hiện tại chứ không chỉ dữ liệu.
        threshold = fields.Datetime.now() - timedelta(seconds=AGENT_ALIVE_WINDOW_SECONDS)
        for agent in self:
            if not agent.last_seen:
                agent.agent_status = 'never'
            else:
                agent.agent_status = 'alive' if agent.last_seen >= threshold else 'dead'

    # Không phụ thuộc field nào của bản ghi: chỉ phụ thuộc web.base.url, đọc lại mỗi lần.
    @api.depends()
    def _compute_setup_command(self):
        """Lệnh dán một phát vào PowerShell trên máy chạy Claude.

        Truyền sẵn địa chỉ Odoo để script khỏi phải hỏi — người cài chỉ còn gõ mã.
        """
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        for agent in self:
            agent.setup_command = (
                "$env:HLV_ODOO_URL='%s'; irm %s/product_agent/download/setup | iex" % (base, base)
            )

    def action_generate_enroll_code(self):
        """Sinh mã cài đặt: người cài gõ mã ngắn này thay vì chép tay token.

        Dùng xong là huỷ, và hết hạn sau ENROLL_CODE_TTL_MINUTES, nên lộ ra ngoài cũng
        không thành cửa sau lâu dài.
        """
        self.ensure_one()
        self.sudo().write({
            'enroll_code': random_enroll_code(),
            'enroll_code_expiry': fields.Datetime.now() + timedelta(minutes=ENROLL_CODE_TTL_MINUTES),
        })

    @api.model
    def consume_enroll_code(self, code):
        """Đổi mã cài đặt lấy agent, và huỷ mã ngay.

        Nhận: chuỗi người cài gõ, không phân biệt hoa thường và dấu gạch.
        Trả: recordset một agent nếu mã đúng và còn hạn, rỗng nếu sai / hết hạn.
        """
        normalized = normalize_enroll_code(code)
        if len(normalized) != ENROLL_CODE_LENGTH:
            return self.browse()
        candidates = self.sudo().search([
            ('active', '=', True),
            ('enroll_code', '!=', False),
            ('enroll_code_expiry', '>', fields.Datetime.now()),
        ])
        agent = candidates.filtered(lambda a: secrets.compare_digest(
            normalize_enroll_code(a.enroll_code), normalized))[:1]
        if agent:
            # Dùng một lần: huỷ ngay để mã bị chụp màn hình cũng vô dụng.
            agent.write({'enroll_code': False, 'enroll_code_expiry': False})
        return agent

    @api.model
    def _authenticate(self, token):
        """Tra agent từ token. Trả recordset một agent, hoặc rỗng nếu không khớp."""
        if not token or not isinstance(token, str):
            return self.browse()
        for agent in self.sudo().search([('active', '=', True)]):
            # So sánh thời gian hằng: không để lộ token qua độ trễ phản hồi.
            if secrets.compare_digest(agent.token or '', token):
                return agent
        return self.browse()

    def touch(self, version):
        """Ghi nhận agent vừa gọi."""
        self.ensure_one()
        self.sudo().write({
            'last_seen': fields.Datetime.now(),
            'version': (version or '')[:64],
        })

    @api.model
    def is_any_online(self):
        """Có ít nhất một agent đang chạy không — để khung chat báo sale biết máy tắt."""
        threshold = fields.Datetime.now() - timedelta(seconds=AGENT_ALIVE_WINDOW_SECONDS)
        return bool(self.sudo().search_count([
            ('active', '=', True), ('last_seen', '>=', threshold),
        ]))

    def action_regenerate_token(self):
        for agent in self:
            agent.sudo().token = secrets.token_urlsafe(32)
