# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .vendor_quote_utils import best_price_ids

VAT_SELECTION = [
    ("0", "0%"),
    ("5", "5%"),
    ("8", "8%"),
    ("10", "10%"),
    ("kct", "Không chịu thuế"),
]
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
    vat = fields.Selection(VAT_SELECTION, string="VAT", copy=False)
    tax_rate = fields.Float(string="% VAT", compute="_compute_tax_rate", store=True)
    delivery_days = fields.Integer(string="Giao sau (ngày)", aggregator="min", copy=False)
    vendor_note = fields.Char(string="Ghi chú NCC", copy=False)
    unavailable = fields.Boolean(string="Không có hàng", copy=False)
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
    selection_state = fields.Selection(
        SELECTION_STATES, string="Lựa chọn", compute="_compute_selection_state"
    )

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

    @api.depends("price_unit", "unavailable", "quote_state", "request_line_id")
    def _compute_is_best_price(self):
        """So giữa các NCC cùng một dòng YCMH, theo đơn giá chưa VAT như core so RFQ.

        Giá chưa VAT vì VAT đầu vào được khấu trừ — so sau VAT sẽ thiên vị hàng
        không chịu thuế.
        """
        request_lines = self.request_line_id
        siblings = self.search([
            ("request_line_id", "in", request_lines.ids),
            ("quote_state", "in", COMPARED_STATES),
            ("unavailable", "=", False),
        ]) if request_lines else self.browse()
        best_ids = best_price_ids(
            (line.id, line.request_line_id.id, line.price_unit) for line in siblings
        )
        for line in self:
            line.is_best_price = line.id in best_ids

    @api.depends("selected", "request_line_id")
    def _compute_selection_state(self):
        """Đã chọn / NCC khác đã được chọn cho cùng mặt hàng / mặt hàng chưa chốt NCC nào."""
        request_lines = self.request_line_id
        chosen_request_line_ids = set(self.search([
            ("request_line_id", "in", request_lines.ids),
            ("selected", "=", True),
        ]).request_line_id.ids) if request_lines else set()
        for line in self:
            if line.selected:
                line.selection_state = "selected"
            elif line.request_line_id.id in chosen_request_line_ids:
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
        if request_line.purchase_lines.filtered(lambda l: l.state != "cancel"):
            raise UserError(_(
                "%s đã lên RFQ/PO. Chọn lại NCC ở đây không đổi được đơn đã tạo.",
                request_line.name or request_line.product_id.display_name,
            ))

        previous = self.search([
            ("request_line_id", "=", request_line.id),
            ("selected", "=", True),
            ("id", "!=", self.id),
        ])
        previous.write({"selected": False})
        self.selected = True
        request_line.write(self._request_line_actual_vals())
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
