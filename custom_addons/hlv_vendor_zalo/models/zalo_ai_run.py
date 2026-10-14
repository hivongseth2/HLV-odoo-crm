# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models

RUN_STATES = [
    ("proposed", "Có đề xuất"),
    ("nothing", "NCC chưa nói gì về báo giá đang mở"),
    ("no_quote", "Không có báo giá đang mở — không gọi AI"),
    ("error", "Lỗi"),
]
# Nhật ký chỉ để theo dõi gần đây — giữ chừng này ngày, cron tự xoá cũ hơn.
KEEP_DAYS = 30


class ZaloAiRun(models.Model):
    """Một lượt AI đọc một nhóm (models/zalo_ai.py) — kể cả lượt không ra gì / lỗi, để biết AI đã nhận tin chưa, đang
    đọc gì, ra gì, tốn bao nhiêu token."""

    _name = "hlv.zalo.ai.run"
    _description = "Nhật ký AI đọc nhóm Zalo"
    _order = "id desc"

    group_id = fields.Many2one("hlv.zalo.group", string="Nhóm", required=True, index=True, ondelete="cascade")
    partner_id = fields.Many2one(related="group_id.partner_id", string="NCC")
    state = fields.Selection(RUN_STATES, string="Kết quả", required=True, default="nothing")
    manual = fields.Boolean(string="Bấm tay", help="Bấm \"AI đọc ngay\" trên nhóm (không phải cron).")
    new_count = fields.Integer(string="Tin mới phía NCC", help="Số tin phía NCC sau lượt đọc trước.")
    message_count = fields.Integer(string="Tin đưa AI đọc")
    quote_count = fields.Integer(string="Báo giá đang mở")
    from_message_id = fields.Integer(string="Từ sau tin #")
    to_message_id = fields.Integer(string="Đến tin #")
    proposal_ids = fields.Many2many("hlv.zalo.proposal", string="Đề xuất")
    summary = fields.Text(string="AI tóm tắt")
    error = fields.Text(string="Lỗi")
    model = fields.Char(string="Model")
    input_tokens = fields.Integer(string="Token vào")
    output_tokens = fields.Integer(string="Token ra")
    duration = fields.Float(string="Thời gian (giây)", digits=(10, 1))

    @api.model
    def _gc(self):
        """Xoá nhật ký cũ hơn KEEP_DAYS ngày (gọi đầu mỗi lượt cron)."""
        self.search([("create_date", "<", fields.Datetime.now() - timedelta(days=KEEP_DAYS))]).unlink()
