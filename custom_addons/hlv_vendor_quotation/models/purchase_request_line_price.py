# -*- coding: utf-8 -*-
"""Khoá giá dòng YCMH gắn với phiếu hỏi giá: thu mua không sửa đơn giá / thuế / chiết khấu trên YCMH (cả cột "sale đề
xuất" lẫn "thực mua") — giá là giá NCC báo trên trang hỏi giá, sale chọn. Muốn giá khác: tạo RFQ rồi "Đề xuất giá"
trên dòng đơn mua (po_price_proposal.py). YCMH không gắn với hỏi giá xử lý như cũ.

Đây là nơi duy nhất định nghĩa "gắn với hỏi giá" — dòng đơn mua (purchase_order_line_price) và wizard Tạo RFQ đọc lại
hlv_price_locked của dòng YCMH.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .purchase_order_line_price import PRICE_WRITE_CTX

# Ô quyết định giá mua của dòng YCMH (misa_purchase_request_sync): bộ "sale đề xuất" và bộ "thực mua" wizard Tạo RFQ
# dùng. Không gồm estimated_cost — chỉ là giá dự trù, wizard lấy giá từ hai bộ này (khoá ở view).
LOCKED_REQUEST_PRICE_FIELDS = (
    "misa_price_before_tax", "misa_tax_rate", "misa_tax_amount", "misa_discount_rate", "misa_discount_amount",
    "misa_price_after_tax", "actual_price_unit", "actual_tax_id", "actual_tax_rate", "actual_discount_rate",
    "actual_discount_amount",
)


class PurchaseRequestLinePriceLock(models.Model):
    _inherit = "purchase.request.line"

    hlv_price_locked = fields.Boolean(
        string="Giá theo hỏi giá", compute="_compute_hlv_price_locked",
        help="Dòng gắn với phiếu hỏi giá (lên từ trang Hỏi giá NCC, hoặc có báo giá NCC của phiếu trỏ vào): giá không "
             "sửa tay được — tạo RFQ rồi bấm \"Đề xuất giá\" trên dòng đơn mua để sale hỏi lại NCC.",
    )

    # Liên kết báo giá → dòng YCMH nằm ở dòng báo giá (request_line_id / backorder_request_line_id), không có trường
    # ngược để khai depends; field không lưu nên mỗi lần đọc đều tính lại.
    @api.depends("request_id.hlv_from_quote_page")
    def _compute_hlv_price_locked(self):
        lines = self.sudo().filtered("id")
        quoted = self.env["hlv.vendor.quote.line"].sudo().search([
            ("inquiry_line_id", "!=", False),
            "|", ("request_line_id", "in", lines.ids), ("backorder_request_line_id", "in", lines.ids),
        ]) if lines else self.env["hlv.vendor.quote.line"]
        linked = set((quoted.request_line_id | quoted.backorder_request_line_id).ids)
        for line in self:
            line.hlv_price_locked = line.id in linked or line.sudo().request_id.hlv_from_quote_page

    def _hlv_price_key(self):
        """Giá trị các ô giá của dòng — so trước / sau khi ghi."""
        self.ensure_one()
        return tuple(
            tuple(self[name].ids) if self._fields[name].type == "many2one" else round(self[name] or 0.0, 4)
            for name in LOCKED_REQUEST_PRICE_FIELDS if name in self._fields
        )

    def write(self, vals):
        # Code hệ thống ghi giá bằng sudo (trang hỏi giá ghi giá NCC đã chọn, đồng bộ MISA…) — chỉ chặn người dùng sửa
        # tay ở backend, mà backend thì không chạy sudo.
        if (self.env.su or self.env.context.get(PRICE_WRITE_CTX)
                or not any(name in vals for name in LOCKED_REQUEST_PRICE_FIELDS)):
            return super().write(vals)
        locked = self.filtered("hlv_price_locked")
        before = {line.id: line._hlv_price_key() for line in locked}
        result = super().write(vals)
        changed = locked.filtered(lambda l: l._hlv_price_key() != before[l.id])
        if changed:
            raise UserError(_(
                "%s gắn với phiếu hỏi giá — không sửa đơn giá / thuế / chiết khấu trên YCMH. Giá là giá sale đã chọn; "
                "muốn giá khác thì tạo RFQ rồi bấm \"Đề xuất giá\" trên dòng đơn mua để sale hỏi lại NCC.",
                ", ".join(changed.mapped(lambda l: l.product_id.display_name or l.name or "")),
            ))
        return result
