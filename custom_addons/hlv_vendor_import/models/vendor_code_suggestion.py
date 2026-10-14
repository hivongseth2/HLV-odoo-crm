# -*- coding: utf-8 -*-
"""Gợi ý khớp mã NCC ↔ sản phẩm bên mình khi KHÔNG trùng mã chắc chắn (mã gần giống, chỉ khớp theo tên): AI đề xuất,
sale của phiếu hỏi giá hoặc quản lý xác nhận. Chưa xác nhận thì bảng giá chưa gắn sản phẩm — đề xuất giá không dùng.

Chỉ dò cho sản phẩm ĐANG được hỏi giá với NCC (vendor_code_suggest.py), không dò cả bảng giá vài trăm dòng.
"""

from odoo import fields, models
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import format_vn_number

from ..services.review_payload import VERDICTS

# Trang sale / quản lý xác nhận gợi ý của một báo giá: /khop-ma-ncc/<id báo giá> (controllers/code_suggestion_page.py).
SUGGESTION_ROUTE = "/khop-ma-ncc"
SUGGESTION_STATES = [
    ("pending", "Chờ xác nhận"),
    ("confirmed", "Đúng"),
    ("rejected", "Không phải"),
    # AI đã xét, không mã NCC nào là sản phẩm này — giữ lại để không hỏi lại (xoá khi nhập bảng giá mới của NCC).
    ("none", "AI: không có mã nào khớp"),
]


class HlvVendorCodeSuggestion(models.Model):
    _name = "hlv.vendor.code.suggestion"
    _description = "Gợi ý khớp mã NCC"
    _order = "id desc"

    partner_id = fields.Many2one("res.partner", "Nhà cung cấp", required=True, index=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", "Sản phẩm bên mình", required=True, index=True, ondelete="cascade")
    price_id = fields.Many2one("hlv.vendor.price", "Dòng bảng giá NCC", ondelete="cascade")
    match_key = fields.Char(related="price_id.match_key", store=True, string="Khoá mã NCC")
    vendor_code = fields.Char(related="price_id.vendor_code", string="Mã NCC")
    vendor_name = fields.Char(related="price_id.vendor_name", string="Tên theo NCC")
    quote_id = fields.Many2one("hlv.vendor.quote", "Báo giá NCC", index=True, ondelete="set null",
                               help="Báo giá đang hỏi sản phẩm này — sale của phiếu là người xác nhận.")
    sale_code = fields.Char(related="quote_id.inquiry_id.sale_code", store=True, string="Mã sale")
    verdict = fields.Selection(VERDICTS, "AI kết luận")
    reason = fields.Char("Lý do")
    state = fields.Selection(SUGGESTION_STATES, "Trạng thái", default="pending", required=True, index=True)
    decided_by = fields.Many2one("res.users", "Người xác nhận", readonly=True)
    decided_at = fields.Datetime("Xác nhận lúc", readonly=True)

    def action_confirm(self):
        """Đúng: gắn sản phẩm cho mọi dòng giá / tồn của mã NCC đó + nhớ mã; các gợi ý khác cùng sản phẩm hoặc cùng mã
        NCC của NCC này thôi chờ."""
        for suggestion in self.filtered(lambda s: s.state == "pending" and s.price_id):
            self.env["hlv.vendor.code.match"].link_key(suggestion.partner_id, suggestion.match_key, suggestion.product_id)
            suggestion._decide("confirmed")
            self.search([
                ("id", "!=", suggestion.id), ("partner_id", "=", suggestion.partner_id.id), ("state", "=", "pending"),
                "|", ("product_id", "=", suggestion.product_id.id), ("match_key", "=", suggestion.match_key),
            ])._decide("rejected")
        return True

    def action_reject(self):
        self.filtered(lambda s: s.state == "pending")._decide("rejected")
        return True

    def _decide(self, state):
        self.write({"state": state, "decided_by": self.env.user.id, "decided_at": fields.Datetime.now()})

    def _price_text(self):
        """Giá bảng giá NCC của dòng gợi ý, một dòng chữ cho người xác nhận."""
        self.ensure_one()
        price = self.price_id
        parts = [f"{format_vn_number(price.price_incl)} sau VAT" if price.price_incl else "",
                 f"{format_vn_number(price.price)} chưa VAT" if price.price else "",
                 price.uom_name or "", f"từ {price.date_from.strftime('%d/%m/%Y')}" if price.date_from else ""]
        return " · ".join(part for part in parts if part)
