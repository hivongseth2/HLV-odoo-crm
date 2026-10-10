# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .vendor_quote_utils import availability_text, best_price_ids, price_incl_vat

VAT_SELECTION = [
    ("0", "0%"),
    ("5", "5%"),
    ("8", "8%"),
    ("10", "10%"),
    ("kct", "Không chịu thuế"),
]
# VAT chọn sẵn trên form NCC cho dòng chưa có VAT — đa số hàng chịu 8%; NCC sửa nếu khác.
DEFAULT_VENDOR_VAT = "8"
SELECTION_STATES = [
    ("selected", "Đã chọn"),
    ("other", "Đã chọn NCC khác"),
    ("pending", "Chưa chọn"),
]
# Sale tạo yêu cầu báo giá, nhưng chốt NCC là việc của thu mua.
SELECTOR_GROUP = "purchase.group_purchase_user"
# Chỉ báo giá NCC đã gửi mới tham gia so sánh; dòng "đang chờ" giá 0 không phải giá rẻ nhất.
COMPARED_STATES = ("quoted", "done")


class VendorQuoteLine(models.Model):
    _name = "hlv.vendor.quote.line"
    _description = "Dòng báo giá nhà cung cấp"
    _order = "quote_id, sequence, id"

    quote_id = fields.Many2one(
        "hlv.vendor.quote", string="Báo giá", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(string="STT", default=10)
    request_line_id = fields.Many2one(
        "purchase.request.line",
        string="Dòng YCMH",
        ondelete="set null",
        index=True,
    )
    inquiry_line_id = fields.Many2one(
        "hlv.vendor.inquiry.line", string="Sản phẩm trong phiếu hỏi giá", ondelete="set null", index=True
    )
    request_id = fields.Many2one(related="quote_id.request_id", store=True, string="YCMH")
    partner_id = fields.Many2one(related="quote_id.partner_id", store=True, string="Nhà cung cấp")
    quote_state = fields.Selection(related="quote_id.state", store=True, string="Trạng thái báo giá")
    currency_id = fields.Many2one(related="quote_id.currency_id")
    product_id = fields.Many2one("product.product", string="Sản phẩm", required=True)
    image_128 = fields.Image(related="product_id.image_128", string="Ảnh")
    name = fields.Char(string="Mô tả")
    # Dòng nhóm của bảng so sánh gom các NCC cùng một mặt hàng: cộng dồn số lượng / giá
    # là vô nghĩa, nên lấy max số lượng và min giá, min ngày giao (= tốt nhất trong nhóm).
    product_qty = fields.Float(string="Số lượng", digits="Product Unit of Measure", aggregator="max")
    product_uom_id = fields.Many2one("uom.uom", string="ĐVT")

    # Phần NCC điền: copy=False để báo giá nhân bản cho NCC khác bắt đầu trống.
    price_unit = fields.Float(
        string="Đơn giá chưa VAT", digits="Product Price", aggregator="min", copy=False
    )
    # NCC báo kiểu "giá niêm yết − % chiết khấu" (tuỳ chọn): lưu lại để đối chiếu với bảng giá
    # của NCC; price_unit vẫn là giá sau chiết khấu — mọi chỗ so giá / lên YCMH dùng price_unit.
    list_price = fields.Float(string="Đơn giá trước CK", digits="Product Price", copy=False)
    discount = fields.Float(string="% Chiết khấu", digits=(5, 2), copy=False)
    vat = fields.Selection(VAT_SELECTION, string="VAT", copy=False)
    tax_rate = fields.Float(string="% VAT", compute="_compute_tax_rate", store=True)
    delivery_days = fields.Integer(string="Giao sau (ngày)", aggregator="min", copy=False)
    vendor_note = fields.Char(string="Ghi chú NCC", copy=False)
    invoice_name = fields.Char(
        string="Tên xuất hóa đơn", copy=False,
        help="Tên hàng NCC sẽ ghi trên hóa đơn — NCC điền khi báo giá, có thể khác tên hàng bên mình.",
    )
    unavailable = fields.Boolean(string="Không có hàng", copy=False)
    # NCC không đủ SL hỏi: "Có ngay" + phần còn lại hẹn ngày giao hoặc "Không có thêm"
    # (vendor_quote_utils.read_availability). available_qty = 0 nghĩa là CÓ ĐỦ — có 0 cái là hết hàng (×).
    available_qty = fields.Float(
        string="Có ngay", digits="Product Unit of Measure", copy=False,
        help="Số lượng NCC giao được ngay khi không đủ số lượng hỏi. 0 = có đủ.",
    )
    backorder_date = fields.Date(string="Hẹn giao phần còn lại", copy=False)
    no_more = fields.Boolean(string="Không có thêm", copy=False,
                             help="NCC chỉ có phần \"Có ngay\", không giao thêm phần còn lại.")
    price_subtotal = fields.Monetary(
        string="Thành tiền chưa VAT",
        compute="_compute_price",
        store=True,
        currency_field="currency_id",
        aggregator="min",
    )
    price_total = fields.Monetary(
        string="Thành tiền sau VAT",
        compute="_compute_price",
        store=True,
        currency_field="currency_id",
        aggregator="min",
    )
    is_best_price = fields.Boolean(string="Giá tốt nhất", compute="_compute_is_best_price")
    selected = fields.Boolean(string="Đã chọn", readonly=True, copy=False)
    inherited_from_id = fields.Many2one(
        "hlv.vendor.quote.line", string="Giá kế thừa từ", readonly=True, copy=False, ondelete="set null",
        help="Giá lấy lại từ báo giá trước của cùng NCC, cùng sản phẩm, còn hiệu lực (services/price_reuse.py).",
    )
    vendor_locked = fields.Boolean(
        string="Đã lên đơn mua", compute="_compute_vendor_locked",
        help="Mặt hàng đã lên đơn mua: NCC không sửa giá dòng này nữa (cả NCC không được chọn — "
             "sale cũng không chọn lại được).",
    )
    selection_state = fields.Selection(
        SELECTION_STATES, string="Lựa chọn", compute="_compute_selection_state"
    )

    def _availability_text(self):
        """"có 6/10 · 4 hẹn 20/10/2026" khi NCC không đủ hàng; đủ / hết hàng → ""."""
        self.ensure_one()
        if self.unavailable:
            return ""
        return availability_text(self.product_qty, self.available_qty, self.backorder_date, self.no_more)

    @api.depends("vat")
    def _compute_tax_rate(self):
        for line in self:
            line.tax_rate = float(line.vat) if line.vat and line.vat != "kct" else 0.0

    @api.depends("price_unit", "product_qty", "tax_rate", "unavailable")
    def _compute_price(self):
        for line in self:
            subtotal = 0.0 if line.unavailable else line.price_unit * line.product_qty
            line.price_subtotal = subtotal
            line.price_total = subtotal * (1 + line.tax_rate / 100.0)

    def _compare_key(self):
        """Nhóm so giá của dòng: cùng sản phẩm trong một phiếu hỏi giá (luồng sale), hoặc cùng
        dòng YCMH (luồng thu mua hỏi giá từ YCMH). Ưu tiên phiếu: sau khi phiếu lên YCMH, chỉ
        dòng được chọn mới gắn dòng YCMH — nhóm theo YCMH sẽ tách nó khỏi các NCC còn lại."""
        self.ensure_one()
        if self.inquiry_line_id:
            return ("inquiry", self.inquiry_line_id.id)
        return ("request", self.request_line_id.id) if self.request_line_id else None

    def _compare_siblings(self, extra_domain):
        """Mọi dòng báo giá cùng nhóm so giá với self (gồm self), lọc thêm extra_domain."""
        inquiry_lines = self.inquiry_line_id
        request_lines = self.filtered(lambda l: not l.inquiry_line_id).request_line_id
        if not inquiry_lines and not request_lines:
            return self.browse()
        return self.search([
            "|",
            ("inquiry_line_id", "in", inquiry_lines.ids),
            "&", ("inquiry_line_id", "=", False), ("request_line_id", "in", request_lines.ids),
        ] + extra_domain)

    @api.depends("price_unit", "tax_rate", "unavailable", "quote_state", "request_line_id", "inquiry_line_id")
    def _compute_is_best_price(self):
        """So giữa các NCC cùng nhóm (xem _compare_key), theo đơn giá SAU VAT.

        Bên mình đọc và chốt giá theo giá sau VAT (yêu cầu của người dùng, 10/2026) — dù VAT đầu
        vào khấu trừ được, NCC 10% và NCC 8% cùng giá chưa VAT thì NCC 8% vẫn được coi là rẻ hơn.
        """
        siblings = self._compare_siblings([
            ("quote_state", "in", COMPARED_STATES),
            ("unavailable", "=", False),
        ])
        best_ids = best_price_ids(
            (line.id, line._compare_key(), line.price_unit * (1 + line.tax_rate / 100.0)) for line in siblings
        )
        for line in self:
            line.is_best_price = line.id in best_ids

    @api.depends("selected", "request_line_id", "inquiry_line_id")
    def _compute_selection_state(self):
        """Đã chọn / NCC khác đã được chọn cho cùng mặt hàng / mặt hàng chưa chốt NCC nào."""
        chosen_keys = {line._compare_key() for line in self._compare_siblings([("selected", "=", True)])}
        for line in self:
            if line.selected:
                line.selection_state = "selected"
            elif line._compare_key() in chosen_keys:
                line.selection_state = "other"
            else:
                line.selection_state = "pending"

    @api.onchange("product_id")
    def _onchange_product_id(self):
        """Dòng sale nhập tay: lấy sẵn tên và ĐVT mua của sản phẩm."""
        if self.product_id and not self.request_line_id:
            self.name = self.product_id.display_name
            self.product_uom_id = self.product_id.uom_po_id or self.product_id.uom_id

    def _check_can_select(self):
        if not self.env.user.has_group(SELECTOR_GROUP):
            raise AccessError(_("Chỉ thu mua mới được chọn / bỏ chọn nhà cung cấp."))

    def action_choose(self):
        """Sale chọn NCC cho một sản phẩm trong phiếu hỏi giá.

        Chưa lên YCMH: chỉ đánh dấu lựa chọn. Đã lên YCMH (VD NCC đã chọn báo hết hàng sau
        đó): đổi luôn NCC + giá trên dòng YCMH — miễn dòng đó chưa lên RFQ/đơn mua.
        Khác action_select (thu mua chọn trên dòng YCMH của luồng hỏi giá từ YCMH).
        """
        self.ensure_one()
        inquiry_line = self.inquiry_line_id
        if not inquiry_line:
            raise UserError(_("Dòng báo giá này không thuộc phiếu hỏi giá nào."))
        if inquiry_line.inquiry_id.state in ("cancel", "closed"):
            raise UserError(_(
                "Phiếu %s đã đóng — lập phiếu mới, giá còn hiệu lực sẽ được dùng lại.", inquiry_line.inquiry_id.name,
            ))
        if self.unavailable or not self.price_unit:
            raise UserError(_("NCC chưa báo giá cho mặt hàng này."))
        self._check_not_ordered(inquiry_line)
        previous = (inquiry_line.quote_line_ids - self).filtered("selected")
        previous.write({"selected": False, "request_line_id": False})
        self.selected = True
        request_line = inquiry_line._live_request_line()
        if request_line:
            self.request_line_id = request_line
            # Sale chỉ có quyền đọc YCMH; ghi đúng các field NCC/giá đã chọn.
            request_line.sudo().write(self._request_line_choice_vals(request_line))
            partial = request_line.sudo().purchased_qty > 0
            request_line.request_id.sudo().message_post(body=Markup(_(
                "Sale đổi NCC cho <i>%(product)s</i> sang <b>%(vendor)s</b>: %(price)s chưa VAT (%(inquiry)s).%(rest)s"
            )) % {
                "product": inquiry_line.name or inquiry_line.product_id.display_name,
                "vendor": self.partner_id.commercial_partner_id.display_name,
                "price": self.currency_id.format(self.price_unit),
                "inquiry": inquiry_line.inquiry_id.name,
                # Đã đặt một phần: nhắc thu mua tạo RFQ cho phần còn thiếu.
                "rest": Markup(_(" Còn phải mua <b>%s</b> — tạo RFQ cho phần này.")) % request_line._hlv_remaining_qty()
                if partial else "",
            })
        return True

    def action_unchoose(self):
        for line in self.filtered("selected"):
            if line.inquiry_line_id._live_request_line():
                raise UserError(_(
                    "Sản phẩm này đã lên YCMH — bấm chọn NCC khác để đổi, không bỏ trống được."
                ))
        self.write({"selected": False})
        return True

    @api.model
    def _check_not_ordered(self, inquiry_line):
        if inquiry_line.locked:
            raise UserError(_(
                "%s đã lên RFQ/đơn mua đủ số lượng — đổi NCC ở đây không đổi được đơn đã tạo. NCC "
                "giao thiếu / hết hàng: nhờ thu mua sửa số lượng dòng đơn mua xuống đúng số NCC giao "
                "được, rồi chọn NCC khác cho phần còn thiếu.",
                inquiry_line.name or inquiry_line.product_id.display_name,
            ))

    @api.depends("inquiry_line_id.locked", "request_line_id.purchased_qty", "request_line_id.product_qty",
                 "request_line_id.purchase_lines.state")
    def _compute_vendor_locked(self):
        for line in self:
            if line.inquiry_line_id:
                line.vendor_locked = line.inquiry_line_id.locked
            else:
                line.vendor_locked = bool(line.request_line_id) and line.request_line_id._hlv_fully_ordered()

    def write(self, vals):
        if "invoice_name" not in vals:
            return super().write(vals)
        old_names = {line.id: line.invoice_name or "" for line in self}
        result = super().write(vals)
        for line in self:
            line._hlv_sync_invoice_name(old_names[line.id])
        return result

    def _hlv_sync_invoice_name(self, old_name):
        """Đẩy tên xuất hóa đơn mới xuống dòng đơn mua của NCC này cho mặt hàng — chỉ dòng đang
        trống hoặc còn đúng tên cũ (tên thu mua sửa tay trên đơn mua thì giữ)."""
        vendor = self.quote_id.access_id.partner_id or self.partner_id.commercial_partner_id
        po_lines = self._hlv_request_line().sudo().purchase_lines.filtered(
            lambda l: l.state != "cancel" and l.order_id.partner_id.commercial_partner_id == vendor
            and (l.hlv_invoice_name or "") in ("", old_name)
        )
        if po_lines:
            po_lines.write({"hlv_invoice_name": self.invoice_name or False})

    def _hlv_request_line(self):
        """Dòng YCMH của mặt hàng này — qua phiếu hỏi giá, hoặc gắn thẳng (luồng hỏi giá từ YCMH)."""
        self.ensure_one()
        return self.inquiry_line_id.request_line_id or self.request_line_id

    def _hlv_ordered_from_vendor(self):
        """NCC của dòng này đang có hàng trên đơn mua cho mặt hàng (kể cả khi sale đã chọn NCC
        khác cho phần còn thiếu) — để trang NCC không gạch dòng NCC vẫn đang giao."""
        self.ensure_one()
        vendor = self.quote_id.access_id.partner_id or self.partner_id.commercial_partner_id
        return bool(self._hlv_request_line().sudo().purchase_lines.filtered(
            lambda l: l.state in ("purchase", "done") and l.product_qty > 0
            and l.order_id.partner_id.commercial_partner_id == vendor
        ))

    def _request_line_choice_vals(self, request_line):
        """NCC + giá đã chọn ghi xuống dòng YCMH, kèm số lượng cần mua = phần CÒN THIẾU: wizard
        "Tạo RFQ" ưu tiên actual_qty của dòng YCMH, mà lần tạo RFQ trước đã ghi actual_qty = cả
        số lượng — không ghi lại thì RFQ cho NCC mới ra lại cả số lượng thay vì phần còn thiếu."""
        return dict(self._request_line_actual_vals(), actual_qty=request_line._hlv_remaining_qty())

    def action_select(self):
        """Chốt NCC cho dòng YCMH: ghi NCC + giá vào actual_* để wizard "Tạo RFQ" dùng luôn."""
        self.ensure_one()
        self._check_can_select()
        request_line = self.request_line_id
        if not request_line:
            raise UserError(_(
                "Dòng báo giá này chưa gắn với dòng YCMH nào. Gắn YCMH cho báo giá "
                "(hoặc chọn dòng YCMH ở cột \"Dòng YCMH\") rồi chọn lại."
            ))
        if self.unavailable or not self.price_unit:
            raise UserError(_("NCC chưa báo giá cho mặt hàng này."))
        if request_line._hlv_fully_ordered():
            raise UserError(_(
                "%s đã lên RFQ/PO đủ số lượng. Chọn lại NCC ở đây không đổi được đơn đã tạo — NCC "
                "giao thiếu / hết hàng thì sửa số lượng dòng đơn mua xuống rồi chọn lại cho phần còn thiếu.",
                request_line.name or request_line.product_id.display_name,
            ))

        previous = self.search([
            ("request_line_id", "=", request_line.id),
            ("selected", "=", True),
            ("id", "!=", self.id),
        ])
        previous.write({"selected": False})
        self.selected = True
        request_line.write(self._request_line_choice_vals(request_line))
        # Markup(...) % dict để tên NCC / mô tả hàng được escape.
        body = Markup(_(
            "Chọn <b>%(vendor)s</b> cho <i>%(product)s</i>: %(price)s/%(uom)s chưa VAT (%(quote)s)."
        )) % {
            "vendor": self.partner_id.display_name,
            "product": request_line.name or request_line.product_id.display_name,
            "price": self.currency_id.format(self.price_unit),
            "uom": self.product_uom_id.name or "",
            "quote": self.quote_id.name,
        }
        request_line.request_id.message_post(body=body)
        return True

    def action_unselect(self):
        if self.filtered("selected"):
            self._check_can_select()
        for line in self.filtered("selected"):
            request_line = line.request_line_id
            line.selected = False
            # Chỉ xoá actual_* khi nó vẫn là của báo giá này; người mua có thể đã sửa tay.
            if request_line and request_line.actual_supplier_id == line.partner_id:
                request_line.write({
                    "actual_supplier_id": False,
                    "actual_price_unit": 0.0,
                    "actual_tax_rate": 0.0,
                    "actual_tax_id": False,
                })
        return True

    def _request_line_actual_vals(self):
        return {
            "actual_supplier_id": self.partner_id.id,
            "actual_price_unit": self.price_unit,
            "actual_tax_rate": self.tax_rate,
            # Phải ghi cả actual_tax_id: wizard Tạo RFQ ưu tiên thuế MISA khi dòng chưa có
            # actual_tax_id, nên chỉ ghi % thì VAT NCC báo sẽ bị thuế đề xuất của sale đè.
            "actual_tax_id": self._purchase_tax().id,
        }

    def _request_line_proposal_vals(self):
        """NCC + giá sale chọn ở trang hỏi giá, ghi vào bộ cột "sale đề xuất" của dòng YCMH — cùng
        bộ cột đồng bộ MISA điền cho YCMH lập trên MISA, để YCMH hiện NCC / giá / thuế / tổng tiền
        như cũ (ba cột tổng tự tính từ đơn giá, % thuế, giá sau thuế và số lượng)."""
        return {
            "sale_proposed_supplier_id": self.partner_id.id,
            "misa_price_before_tax": self.price_unit,
            "misa_tax_rate": self.tax_rate,
            "misa_price_after_tax": price_incl_vat(self.price_unit, self.tax_rate),
        }

    def _purchase_tax(self):
        if not self.vat or self.vat == "kct":
            return self.env["account.tax"]
        company = self.quote_id.company_id or self.env.company
        return self.env["account.tax"].with_company(company).search([
            ("type_tax_use", "=", "purchase"),
            ("amount_type", "=", "percent"),
            ("amount", "=", self.tax_rate),
            ("company_id", "=", company.id),
        ], limit=1)
