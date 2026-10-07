# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.notify import post_internal

# Trạng thái NCC tự báo trên trang báo giá của họ — thứ tự là thứ tự tiến trình.
VENDOR_STATUS = [
    ("packed", "Đã đóng gói"),
    ("delivered", "Đã giao"),
]
VENDOR_STATUS_ORDER = [key for key, _label in VENDOR_STATUS]


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    hlv_vendor_status = fields.Selection(
        VENDOR_STATUS, string="NCC báo", copy=False, tracking=True,
        help="Nhà cung cấp tự cập nhật trên trang báo giá của họ.",
    )
    hlv_vendor_status_date = fields.Datetime(string="NCC báo lúc", copy=False, readonly=True)
    hlv_vendor_quote_ids = fields.Many2many(
        "hlv.vendor.quote", string="Báo giá NCC", compute="_compute_hlv_vendor_links"
    )
    hlv_inquiry_ids = fields.Many2many(
        "hlv.vendor.inquiry", string="Phiếu hỏi giá", compute="_compute_hlv_vendor_links"
    )

    @api.depends("order_line.purchase_request_lines")
    def _compute_hlv_vendor_links(self):
        """Ngược chuỗi đơn mua → dòng YCMH → dòng báo giá NCC đã được chọn → báo giá / phiếu."""
        QuoteLine = self.env["hlv.vendor.quote.line"]
        for order in self:
            request_lines = order.order_line.purchase_request_lines
            chosen = QuoteLine.search([
                ("request_line_id", "in", request_lines.ids),
                ("selected", "=", True),
            ]) if request_lines else QuoteLine
            order.hlv_vendor_quote_ids = chosen.quote_id
            order.hlv_inquiry_ids = chosen.inquiry_line_id.inquiry_id

    def _chat_contacts(self):
        """Người trong công ty cần biết khi NCC nhắn trên đơn mua: người mua + sale tạo phiếu."""
        self.ensure_one()
        return (self.user_id | self.hlv_inquiry_ids.user_id).partner_id

    def _vendor_set_status(self, status, vendor_partner):
        """NCC báo tiến độ từ trang công khai. Chỉ đi tới (đóng gói → đã giao), không lùi."""
        self.ensure_one()
        if status not in VENDOR_STATUS_ORDER:
            raise UserError(_("Trạng thái không hợp lệ."))
        current = VENDOR_STATUS_ORDER.index(self.hlv_vendor_status) if self.hlv_vendor_status else -1
        if VENDOR_STATUS_ORDER.index(status) <= current:
            return False
        self.write({"hlv_vendor_status": status, "hlv_vendor_status_date": fields.Datetime.now()})
        # Ghi chú nội bộ: NCC là follower của đơn mua của họ — đăng "comment" sẽ email ra ngoài.
        post_internal(self, Markup(_("NCC báo đơn <b>%s</b>.")) % dict(VENDOR_STATUS)[status], vendor_partner)
        return True
