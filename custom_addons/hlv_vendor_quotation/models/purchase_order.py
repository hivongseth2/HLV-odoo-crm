# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.notify import post_internal
from .vendor_quote_utils import normalize_origin

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

    @api.depends("order_line.purchase_request_lines", "partner_id")
    def _compute_hlv_vendor_links(self):
        """Ngược chuỗi đơn mua → dòng YCMH → phiếu hỏi giá, và báo giá của CHÍNH NCC của đơn.

        Không dựa vào "dòng đang được chọn": NCC giao thiếu, sale chọn NCC khác cho phần còn
        lại thì đơn cũ vẫn thuộc báo giá của NCC cũ (NCC cũ vẫn thấy đơn, báo tiến độ, in đơn).
        """
        InquiryLine = self.env["hlv.vendor.inquiry.line"]
        QuoteLine = self.env["hlv.vendor.quote.line"]
        for order in self:
            request_lines = order.order_line.purchase_request_lines
            if not request_lines:
                order.hlv_inquiry_ids = order.hlv_vendor_quote_ids = False
                continue
            inquiry_lines = InquiryLine.search([("request_line_id", "in", request_lines.ids)])
            quote_lines = QuoteLine.search([
                "|", ("inquiry_line_id", "in", inquiry_lines.ids), ("request_line_id", "in", request_lines.ids),
            ])
            vendor = order.partner_id.commercial_partner_id
            order.hlv_inquiry_ids = inquiry_lines.inquiry_id
            order.hlv_vendor_quote_ids = quote_lines.quote_id.filtered(
                lambda q: q.state != "cancel" and q.partner_id.commercial_partner_id == vendor
            )

    def write(self, vals):
        result = super().write(vals)
        # Đổi NCC trên RFQ: tên xuất hóa đơn phải là của NCC mới.
        if "partner_id" in vals:
            self.order_line._hlv_fill_invoice_name(overwrite=True)
        return result

    def _chat_contacts(self):
        """Người trong công ty cần biết khi NCC nhắn trên đơn mua: người mua + sale tạo phiếu."""
        self.ensure_one()
        return (self.user_id | self.hlv_inquiry_ids.user_id).partner_id

    def _hlv_set_origin(self, origin):
        """Sale ghi mã đơn hàng của khách vào Tài liệu gốc khi khách chốt mua — lúc hỏi giá
        khách chưa chắc mua nên chưa có. Ghi bằng sudo (sale không có quyền ghi đơn mua):
        controller phải kiểm đơn thuộc phạm vi mã sale trước khi gọi."""
        origin = normalize_origin(origin)
        author = self.env.user.partner_id
        for order in self.sudo():
            if order.state == "cancel":
                raise UserError(_("Đơn mua %s đã huỷ.", order.name))
            old = order.origin or ""
            if old == origin:
                continue
            order.origin = origin or False
            post_internal(order, Markup(_("Sale cập nhật Tài liệu gốc từ trang Hỏi giá NCC: <b>%s</b> → <b>%s</b>.")) % (
                old or _("(trống)"), origin or _("(trống)"),
            ), author)

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


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    # Lưu thật (không tính) để xuất PDF / đẩy MISA dùng được, và thu mua sửa tay được. Không để
    # field tính-lưu: thêm vào lúc nâng cấp module là Odoo tính lại cho TOÀN BỘ dòng đơn mua cũ.
    hlv_invoice_name = fields.Char(
        string="Tên xuất hóa đơn", copy=False,
        help="Tên hàng NCC sẽ ghi trên hóa đơn — NCC điền trên trang báo giá; tự ghi khi dòng đơn "
             "mua lên từ YCMH có báo giá của chính NCC này. Thu mua sửa tay được.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        # Wizard "Tạo RFQ" tạo dòng kèm purchase_request_lines ngay trong vals.
        lines.filtered(lambda l: not l.hlv_invoice_name)._hlv_fill_invoice_name()
        return lines

    def write(self, vals):
        result = super().write(vals)
        # Wizard gộp thêm dòng YCMH vào dòng đơn mua đã có (cùng sản phẩm).
        if "purchase_request_lines" in vals:
            self.filtered(lambda l: not l.hlv_invoice_name)._hlv_fill_invoice_name()
        return result

    def _hlv_vendor_invoice_name(self):
        """Tên xuất hóa đơn NCC của đơn điền cho mặt hàng: dòng đơn mua → dòng YCMH → dòng báo
        giá của đúng NCC của đơn (qua phiếu hỏi giá, hoặc gắn thẳng YCMH). Không có → ""."""
        self.ensure_one()
        request_lines = self.sudo().purchase_request_lines
        if not request_lines:
            return ""
        vendor = self.order_id.partner_id.commercial_partner_id
        candidates = self.env["hlv.vendor.quote.line"].sudo().search([
            ("invoice_name", "!=", False),
            "|", ("inquiry_line_id.request_line_id", "in", request_lines.ids),
            ("request_line_id", "in", request_lines.ids),
        ], order="id desc")
        match = candidates.filtered(lambda q: q.quote_id.partner_id.commercial_partner_id == vendor)[:1]
        return match.invoice_name or ""

    def _hlv_fill_invoice_name(self, overwrite=False):
        """Ghi tên xuất hóa đơn từ báo giá. overwrite=False: chỉ dòng còn trống (giữ tên thu mua
        đã sửa tay)."""
        for line in self:
            if line.hlv_invoice_name and not overwrite:
                continue
            name = line._hlv_vendor_invoice_name()
            if name or overwrite:
                line.hlv_invoice_name = name or False

    @api.model
    def _hlv_backfill_invoice_names(self):
        """Điền cho dòng đơn mua đã có trước khi field được lưu — chỉ dòng có báo giá ghi tên
        xuất hóa đơn (đi từ báo giá sang, không quét cả bảng dòng đơn mua)."""
        quote_lines = self.env["hlv.vendor.quote.line"].sudo().search([("invoice_name", "!=", False)])
        request_lines = quote_lines.inquiry_line_id.request_line_id | quote_lines.request_line_id
        request_lines.sudo().purchase_lines._hlv_fill_invoice_name()
