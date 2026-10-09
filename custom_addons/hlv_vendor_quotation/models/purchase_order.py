# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.notify import post_internal
from .vendor_quote_utils import DELIVERY_CHANH, DELIVERY_CPN, delivery_mode, normalize_origin

# Tiến độ đơn mua trên trang NCC — thứ tự là thứ tự tiến trình. Trống = đã nhận đơn, chờ đóng gói.
# NCC tự báo "Đã đóng gói"; "Đã gửi hàng" chỉ khi đơn gửi CPN / gửi chành (kèm thông tin gửi);
# "Đã giao" tự đặt khi kho bên mình nhận đủ hàng (_hlv_mark_delivered_by_receipt), NCC không bấm.
VENDOR_STATUS = [
    ("packed", "Đã đóng gói"),
    ("shipped", "Đã gửi hàng"),
    ("delivered", "Đã giao"),
]
VENDOR_STATUS_ORDER = [key for key, _label in VENDOR_STATUS]
# Trường Studio trên đơn mua (không có ở mọi môi trường — đọc qua _hlv_studio_text).
DELIVERY_TERM_FIELD = "x_studio_delivery_term"
DELIVERY_PLACE_FIELD = "x_studio_ddgh"
SHIP_TEXT_MAX = 120


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    hlv_vendor_status = fields.Selection(
        VENDOR_STATUS, string="NCC báo", copy=False, tracking=True,
        help="Nhà cung cấp tự cập nhật trên trang báo giá của họ.",
    )
    hlv_vendor_status_date = fields.Datetime(string="NCC báo lúc", copy=False, readonly=True)
    # NCC báo khi gửi CPN / gửi chành: hãng CPN hoặc tên chành, và mã vận đơn hoặc số xe / SĐT tài xế.
    hlv_ship_carrier = fields.Char(string="NCC gửi qua (hãng CPN / chành)", copy=False, readonly=True)
    hlv_ship_ref = fields.Char(string="Mã vận đơn / số xe", copy=False, readonly=True)
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

    def _hlv_studio_text(self, field_name):
        """Chữ trong một trường Studio của đơn mua; môi trường chưa có trường đó → ""."""
        self.ensure_one()
        return (self[field_name] or "").strip() if field_name in self._fields else ""

    def _hlv_delivery_term(self):
        return self._hlv_studio_text(DELIVERY_TERM_FIELD)

    def _hlv_delivery_place(self):
        return self._hlv_studio_text(DELIVERY_PLACE_FIELD)

    def _hlv_delivery_mode(self):
        """Cách giao (vendor_quote_utils.delivery_mode) theo "Phương thức giao hàng" của đơn."""
        return delivery_mode(self._hlv_delivery_term())

    def _hlv_vendor_stage(self):
        """Tab của đơn trên trang NCC: "waiting" (đã nhận, chờ đóng gói), "packed" (đã đóng gói / đã
        gửi), "delivered" (đã giao — kể cả đơn kho đã nhận đủ từ trước khi có tự chuyển)."""
        self.ensure_one()
        if self.hlv_vendor_status == "delivered" or self._hlv_receipts_done():
            return "delivered"
        return "packed" if self.hlv_vendor_status in ("packed", "shipped") else "waiting"

    def _hlv_receipts_done(self):
        """Kho đã nhận xong mọi phiếu NHẬP từ NCC của đơn (có ít nhất một phiếu đã nhận). Chỉ xét
        phiếu nhập (incoming): kho nhận 2 bước thì bước chuyển vào kho sau đó không làm trễ "Đã giao";
        giao thiếu còn phiếu nhập chờ (backorder) thì chưa xong."""
        self.ensure_one()
        receipts = self.sudo().picking_ids.filtered(lambda p: p.picking_type_code == "incoming" and p.state != "cancel")
        return bool(receipts) and all(p.state == "done" for p in receipts)

    def _vendor_set_status(self, status, vendor_partner):
        """NCC báo "Đã đóng gói" từ trang công khai. Chỉ đi tới, không lùi; "Đã gửi hàng" đi qua
        _vendor_mark_shipped (cần thông tin gửi), "Đã giao" tự đặt khi kho nhận hàng."""
        self.ensure_one()
        if status != "packed":
            raise UserError(_("Trạng thái không hợp lệ."))
        return self._hlv_advance_status(status, vendor_partner, Markup(_("NCC báo đơn <b>%s</b>.")) % dict(VENDOR_STATUS)[status])

    def _vendor_mark_shipped(self, carrier, ref, vendor_partner):
        """NCC báo đã gửi CPN / gửi chành, kèm hãng CPN / tên chành và mã vận đơn / số xe. Gửi lại được
        (sửa thông tin) khi đơn chưa giao. Đơn giao thẳng không cần bước này."""
        self.ensure_one()
        mode = self._hlv_delivery_mode()
        if mode not in (DELIVERY_CPN, DELIVERY_CHANH):
            raise UserError(_("Đơn này không gửi CPN / chành — kho bên mua nhận hàng là đơn tự chuyển Đã giao."))
        carrier = " ".join((carrier or "").split())[:SHIP_TEXT_MAX]
        ref = " ".join((ref or "").split())[:SHIP_TEXT_MAX]
        if not ref or (mode == DELIVERY_CHANH and not carrier):
            raise UserError(_("Nhập tên chành và số xe / SĐT tài xế.") if mode == DELIVERY_CHANH
                            else _("Nhập mã vận đơn."))
        if self.hlv_vendor_status == "delivered":
            raise UserError(_("Đơn đã giao — không sửa thông tin gửi được nữa."))
        self.write({"hlv_ship_carrier": carrier or False, "hlv_ship_ref": ref})
        what = _("Gửi chành") if mode == DELIVERY_CHANH else _("Gửi CPN")
        body = Markup(_("NCC báo <b>%s</b>: %s — %s.")) % (what, carrier or "—", ref)
        if not self._hlv_advance_status("shipped", vendor_partner, body):
            post_internal(self, body, vendor_partner)  # đã báo gửi từ trước: chỉ cập nhật thông tin
        return True

    def _hlv_advance_status(self, status, author, body):
        """Đưa tiến độ tới status (không lùi) + ghi chú nội bộ. Trả False nếu đơn đã ở / qua status."""
        current = VENDOR_STATUS_ORDER.index(self.hlv_vendor_status) if self.hlv_vendor_status else -1
        if VENDOR_STATUS_ORDER.index(status) <= current:
            return False
        self.write({"hlv_vendor_status": status, "hlv_vendor_status_date": fields.Datetime.now()})
        # Ghi chú nội bộ: NCC là follower của đơn mua của họ — đăng "comment" sẽ email ra ngoài.
        post_internal(self, body, author)
        return True

    def _hlv_mark_delivered_by_receipt(self):
        """Kho bên mình nhận xong hàng (phiếu nhập đã xác nhận) → đơn tự chuyển "Đã giao" trên trang
        NCC, NCC khỏi bấm. Gọi sau khi xác nhận phiếu nhập (stock.picking._action_done)."""
        for order in self.sudo().filtered(lambda o: o.hlv_vendor_status != "delivered"):
            if order._hlv_receipts_done():
                order._hlv_advance_status(
                    "delivered", self.env.user.partner_id, Markup(_("Kho đã nhận đủ hàng — đơn tự chuyển <b>Đã giao</b>.")),
                )


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
