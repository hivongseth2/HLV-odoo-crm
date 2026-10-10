# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.chat_bus import notify_order_status
from ..services.notify import log_internal, post_internal
from ..services.vendor_chat import post_chat
from .vendor_quote_utils import (
    DATE_FMT, delivery_mode, format_vn_number, local_date_text, normalize_origin, parse_states,
)

_logger = logging.getLogger(__name__)

# Tiến độ đơn mua trên trang NCC — thứ tự là thứ tự tiến trình. Trống = đã nhận đơn, chờ đóng gói.
# NCC tự báo "Đã đóng gói"; "Đã gửi hàng" chỉ khi đơn gửi CPN / gửi chành (kèm thông tin gửi);
# "Đã giao" tự đặt khi kho bên mình nhận đủ hàng (_hlv_mark_delivered_by_receipt), NCC không bấm.
VENDOR_STATUS = [
    ("packed", "Đã đóng gói"),
    ("shipped", "Đã gửi hàng"),
    ("delivered", "Đã giao"),
]
VENDOR_STATUS_ORDER = [key for key, _label in VENDOR_STATUS]
# NCC báo đã gửi hàng bằng cách nào: gửi CPN / chành (cần mã vận đơn / số xe) hay tự chở tới.
SHIP_METHODS = [
    ("cpn", "Gửi CPN / chành"),
    ("self", "NCC tự vận chuyển"),
]
# Trạng thái đơn mua (state của Odoo) admin chọn được để hiện trên trang NCC — Cài đặt → Mua hàng →
# Hỏi giá NCC. Đơn hủy không chọn được: chỉ hiện đơn hủy SAU khi đã xác nhận (NCC cần biết để khỏi giao).
VENDOR_ORDER_STATES = [
    ("draft", "Nháp"),
    ("sent", "RFQ đã gửi"),
    ("to approve", "Chờ duyệt"),
    ("purchase", "Đơn mua hàng"),
    ("done", "Đã khóa"),
]
VENDOR_ORDER_STATE_LABELS = dict(VENDOR_ORDER_STATES, cancel="Đã hủy")
VENDOR_ORDER_STATES_PARAM = "hlv_vendor_quotation.vendor_order_states"
# Đơn đã xác nhận: NCC mới đóng gói / gửi hàng được. Cũng là mặc định hiện trên trang NCC.
CONFIRMED_STATES = ("purchase", "done")
# Nhãn tiến độ trên trang NCC (_hlv_vendor_progress): trạng thái NCC báo + chờ xác nhận / chờ đóng gói / đã hủy.
PROGRESS_LABELS = dict(VENDOR_STATUS, rfq="Chờ xác nhận", waiting="Chờ đóng gói", cancel="Đã hủy")
# Trường Studio trên đơn mua — không có ở mọi môi trường (DB test, cài mới) nên đọc qua _hlv_studio_text.
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
    # NCC báo đã gửi hàng: cách gửi, hãng CPN / tên chành, mã vận đơn / số xe / người giao.
    hlv_ship_method = fields.Selection(SHIP_METHODS, string="NCC gửi hàng bằng", copy=False, readonly=True)
    hlv_ship_carrier = fields.Char(string="Hãng CPN / chành", copy=False, readonly=True)
    hlv_ship_ref = fields.Char(string="Mã vận đơn / số xe / người giao", copy=False, readonly=True)
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
        """Giá trị trường Studio dạng chữ ("" nếu DB không có trường / trường trống). convert_to_export ra
        nhãn của selection, tên của many2one — không ra mã kỹ thuật."""
        self.ensure_one()
        field = self._fields.get(field_name)
        if not field:
            return ""
        return str(field.convert_to_export(self[field_name], self) or "").strip()

    def _hlv_delivery_term(self):
        return self._hlv_studio_text(DELIVERY_TERM_FIELD)

    def _hlv_delivery_place(self):
        return self._hlv_studio_text(DELIVERY_PLACE_FIELD)

    def _hlv_ship_text(self):
        """Thông tin gửi hàng NCC đã báo, một dòng: "Gửi CPN / chành · Viettel Post · VTP123"."""
        self.ensure_one()
        parts = [dict(SHIP_METHODS).get(self.hlv_ship_method, ""), self.hlv_ship_carrier, self.hlv_ship_ref]
        return " · ".join(part for part in parts if part)

    def _hlv_delivery_mode(self):
        """Cách giao (vendor_quote_utils.delivery_mode) theo "Phương thức giao hàng" của đơn."""
        return delivery_mode(self._hlv_delivery_term())

    @api.model
    def _hlv_vendor_visible_states(self):
        """Trạng thái đơn mua hiện trên trang NCC (Cài đặt; chưa cấu hình → đơn đã xác nhận)."""
        param = self.env["ir.config_parameter"].sudo().get_param(VENDOR_ORDER_STATES_PARAM)
        return parse_states(param, [state for state, _label in VENDOR_ORDER_STATES], CONFIRMED_STATES)

    def _hlv_vendor_state_label(self):
        """Trạng thái đơn hiện cho NCC: Nháp / RFQ đã gửi / Chờ duyệt / Đơn mua hàng / Đã khóa / Đã hủy."""
        self.ensure_one()
        return VENDOR_ORDER_STATE_LABELS.get(self.state, "")

    def _hlv_vendor_progress(self):
        """Tiến độ hiện trên trang NCC: "cancel" (đơn đã hủy), "rfq" (chưa xác nhận — NCC chỉ xem),
        "delivered" (đã giao — kể cả đơn kho đã nhận đủ từ trước khi có tự chuyển), "shipped",
        "packed", hoặc "waiting" (chờ đóng gói)."""
        self.ensure_one()
        if self.state == "cancel":
            return "cancel"
        if self.state not in CONFIRMED_STATES:
            return "rfq"
        if self.hlv_vendor_status == "delivered" or self._hlv_receipts_done():
            return "delivered"
        return self.hlv_vendor_status or "waiting"

    def _hlv_vendor_stage(self):
        """Tab của đơn trên trang NCC: như _hlv_vendor_progress, gộp "đã gửi hàng" vào tab "Đã đóng gói"."""
        progress = self._hlv_vendor_progress()
        return "packed" if progress == "shipped" else progress

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
        self._hlv_check_vendor_can_update()
        return self._hlv_advance_status(status, vendor_partner, Markup(_("NCC báo đơn <b>%s</b>.")) % dict(VENDOR_STATUS)[status])

    def _vendor_mark_shipped(self, method, carrier, ref, vendor_partner):
        """NCC báo đã gửi hàng: gửi CPN / chành (bắt buộc mã vận đơn / số xe; hãng / chành tuỳ) hoặc
        NCC tự vận chuyển (người giao / SĐT / biển số tuỳ). Sửa lại được tới khi kho nhận hàng."""
        self.ensure_one()
        self._hlv_check_vendor_can_update()
        if method not in dict(SHIP_METHODS):
            raise UserError(_("Chọn cách gửi hàng."))
        carrier = " ".join((carrier or "").split())[:SHIP_TEXT_MAX] if method == "cpn" else ""
        ref = " ".join((ref or "").split())[:SHIP_TEXT_MAX]
        if method == "cpn" and not ref:
            raise UserError(_("Nhập mã vận đơn (hoặc số xe nếu gửi chành)."))
        if self._hlv_vendor_progress() == "delivered":
            raise UserError(_("Đơn đã giao — không sửa thông tin gửi được nữa."))
        self.write({"hlv_ship_method": method, "hlv_ship_carrier": carrier or False, "hlv_ship_ref": ref or False})
        body = Markup(_("NCC báo <b>đã gửi hàng</b>: %s.")) % self._hlv_ship_text()
        if not self._hlv_advance_status("shipped", vendor_partner, body):
            # Đã báo gửi từ trước: chỉ cập nhật thông tin — vẫn báo sale biết.
            post_internal(self, body, vendor_partner)
            notify_order_status(self)
        return True

    def _hlv_check_vendor_can_update(self):
        """NCC chỉ báo tiến độ trên đơn đã xác nhận: RFQ hiện cho NCC xem trước (tuỳ Cài đặt) nhưng
        giá / số lượng còn đổi được — đóng gói theo RFQ là đóng gói sai."""
        if self.state == "cancel":
            raise UserError(_("Đơn %s đã hủy — không cần giao.", self.name))
        if self.state not in CONFIRMED_STATES:
            raise UserError(_("Đơn %s chưa xác nhận — bên mua xác nhận đơn rồi mới đóng gói / gửi hàng.", self.name))

    def _hlv_advance_status(self, status, author, body, notify_staff=True):
        """Đưa tiến độ tới status (không lùi) + ghi chú nội bộ. Trả False nếu đơn đã ở / qua status.
        notify_staff=False: chỉ ghi chatter, không email follower nội bộ (việc kho tự làm)."""
        current = VENDOR_STATUS_ORDER.index(self.hlv_vendor_status) if self.hlv_vendor_status else -1
        if VENDOR_STATUS_ORDER.index(status) <= current:
            return False
        self.write({"hlv_vendor_status": status, "hlv_vendor_status_date": fields.Datetime.now()})
        # Ghi chú nội bộ: NCC là follower của đơn mua của họ — đăng "comment" sẽ email ra ngoài.
        (post_internal if notify_staff else log_internal)(self, body, author)
        notify_order_status(self)  # trang /hoi-gia-ncc: popup + chuông cho sale
        return True

    # ------------------------------------------------------------------
    # Báo NCC: tin trong khung trao đổi của đơn (trang NCC có chuông, tiếng, số chưa đọc sẵn cho tin
    # bên mua) — đơn xác nhận, đơn hủy, kho đã nhận hàng. Không làm hỏng thao tác của thu mua / kho
    # nếu báo lỗi: chỉ ghi log.
    # ------------------------------------------------------------------
    def _hlv_notify_vendor(self, text):
        for order in self.sudo().filtered("hlv_vendor_quote_ids"):
            try:
                with self.env.cr.savepoint():
                    post_chat(order, text(order), order.company_id.partner_id, from_vendor=False)
            except Exception:  # noqa: BLE001 — thông báo phụ, không chặn xác nhận / nhận hàng
                _logger.exception("Không báo được NCC về đơn mua %s", order.name)

    def button_approve(self, force=False):
        waiting = self.filtered(lambda o: o.state not in CONFIRMED_STATES)
        result = super().button_approve(force=force)
        waiting.filtered(lambda o: o.state in CONFIRMED_STATES)._hlv_notify_vendor(lambda o: _(
            "Đơn mua %(name)s đã xác nhận: %(count)s mặt hàng, %(amount)s sau VAT%(eta)s. Vui lòng chuẩn bị hàng "
            "và bấm \"Đã đóng gói\" khi xong.",
            name=o.name, count=len(o.order_line.filtered(lambda l: not l.display_type)),
            amount=format_vn_number(o.amount_total),
            eta=_(", hàng về dự kiến %s", local_date_text(o.date_planned, DATE_FMT)) if o.date_planned else "",
        ))
        return result

    def button_cancel(self):
        confirmed = self.filtered(lambda o: o.state in CONFIRMED_STATES)
        result = super().button_cancel()
        confirmed.filtered(lambda o: o.state == "cancel")._hlv_notify_vendor(
            lambda o: _("Đơn mua %s đã hủy — quý công ty không cần đóng gói / giao hàng cho đơn này.", o.name)
        )
        return result

    def _hlv_mark_delivered_by_receipt(self):
        """Kho bên mình nhận xong hàng (phiếu nhập đã xác nhận) → đơn tự chuyển "Đã giao" trên trang
        NCC, NCC khỏi bấm. Gọi sau khi xác nhận phiếu nhập (stock.picking._action_done)."""
        for order in self.sudo().filtered(lambda o: o.hlv_vendor_status != "delivered"):
            if order._hlv_receipts_done() and order._hlv_advance_status(
                "delivered", self.env.user.partner_id, Markup(_("Kho đã nhận đủ hàng — đơn tự chuyển <b>Đã giao</b>.")),
                notify_staff=False,  # kho vừa tự bấm nhận — email cả follower đơn mua chỉ là thư rác
            ):
                order._hlv_notify_vendor(lambda o: _("Kho đã nhận đủ hàng đơn %s. Cảm ơn quý công ty!", o.name))


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
