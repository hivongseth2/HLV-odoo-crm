# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models

# Sale thường hỏi trong nhóm ngay trước / sau khi lập phiếu — lấy tin từ trước ngày tạo báo giá một chút.
LOOKBACK_DAYS = 1


class VendorQuote(models.Model):
    """Nút "Tin Zalo" trên báo giá NCC: tin các nhóm Zalo của NCC này từ lúc tạo báo giá. Chỉ thêm nút xem —
    không đổi gì luồng báo giá."""

    _inherit = "hlv.vendor.quote"

    zalo_message_count = fields.Integer(string="Tin Zalo", compute="_compute_zalo_message_count")

    def _zalo_message_domain(self):
        self.ensure_one()
        since = (self.create_date or fields.Datetime.now()) - timedelta(days=LOOKBACK_DAYS)
        return [("partner_id", "=", self.partner_id.commercial_partner_id.id), ("sent_at", ">=", since)]

    @api.depends("partner_id", "create_date")
    def _compute_zalo_message_count(self):
        Message = self.env["hlv.zalo.message"].sudo()
        for quote in self:
            quote.zalo_message_count = Message.search_count(quote._zalo_message_domain()) if quote.partner_id else 0

    def action_open_zalo_messages(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("hlv_vendor_zalo.action_zalo_message")
        action["domain"] = self._zalo_message_domain()
        action["name"] = f"Tin Zalo — {self.partner_id.commercial_partner_id.display_name}"
        return action
