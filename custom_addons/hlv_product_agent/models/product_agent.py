# -*- coding: utf-8 -*-
"""Máy chạy Claude: một bản ghi, một token."""
import secrets
from datetime import timedelta

from odoo import api, fields, models

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
