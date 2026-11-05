# -*- coding: utf-8 -*-
"""Hộp "Đề xuất" trên dòng đơn mua: thu mua sửa giá (sau VAT), SL (0 = không mua nữa), mã thay thế, VAT — điền sẵn
như trên dòng, để nguyên là không đổi — kèm lý do (bắt buộc), không sửa thẳng đơn (dòng lên từ hỏi giá bị khoá, xem models/purchase_order_line_price.py). Sale sửa lại
được trước khi hỏi NCC (models/po_proposal_change.py)."""

from odoo import api, fields, models

from ..models.po_proposal_change import vat_code_of
from ..models.purchase_order_revision import tax_rate_of
from ..models.vendor_quote_utils import price_incl_vat


class PurchaseOrderPriceProposalWizard(models.TransientModel):
    _name = "hlv.po.price.proposal.wizard"
    _description = "Thu mua đề xuất đổi dòng đơn mua"

    order_line_id = fields.Many2one("purchase.order.line", string="Dòng đơn mua", required=True, readonly=True)
    product_id = fields.Many2one(related="order_line_id.product_id", string="Sản phẩm")
    vendor_id = fields.Many2one(related="order_line_id.partner_id", string="Nhà cung cấp")
    uom_id = fields.Many2one(related="order_line_id.product_uom", string="ĐVT")
    current_qty = fields.Float(related="order_line_id.product_qty", string="SL trên đơn")
    current_price_incl = fields.Float(string="Giá trên đơn (sau VAT)", digits="Product Price",
                                      compute="_compute_current_price_incl")
    current_tax_rate = fields.Float(string="% VAT trên đơn", compute="_compute_current_price_incl")
    # Điền sẵn như trên dòng (compute theo dòng, sửa được): để nguyên = không đổi.
    suggested_price_incl = fields.Float(string="Giá gợi ý (sau VAT)", digits="Product Price",
                                        compute="_compute_prefill", store=True, readonly=False,
                                        help="Giá thu mua mong muốn — sale dùng để thương lượng khi hỏi lại NCC. "
                                             "Để nguyên giá trên đơn nếu không gợi ý giá.")
    suggested_qty = fields.Float(string="SL đề xuất", digits="Product Unit of Measure",
                                 compute="_compute_prefill", store=True, readonly=False,
                                 help="Để nguyên nếu không đổi; 0 = không mua nữa (dòng về SL 0). Duyệt xong: tăng thì "
                                      "cộng thêm vào đơn, giảm thì dòng cũ giảm SL.")
    suggested_product_id = fields.Many2one("product.product", string="Đổi sang mã",
                                           domain=[("purchase_ok", "=", True)],
                                           help="Để trống nếu giữ mã. Duyệt xong: dòng mã cũ về SL 0, mã mới thành "
                                                "dòng mới.")
    suggested_vat = fields.Selection(selection="_selection_vat", string="VAT", compute="_compute_prefill", store=True,
                                     readonly=False,
                                     help="Để nguyên nếu giữ VAT. Hỏi NCC thì NCC xác nhận VAT trên trang NCC; không hỏi NCC "
                                          "thì giữ giá chưa VAT, chỉ đổi thuế.")
    note = fields.Text(string="Lý do", required=True,
                       help="VD: NCC khác báo rẻ hơn, khách mua thêm, mã cũ ngừng sản xuất… — sale đọc trên trang Hỏi "
                            "giá NCC.")

    @api.model
    def _selection_vat(self):
        """Chỉ các mức VAT công ty đã khai thuế mua (vendor_quote_line._hlv_vat_options)."""
        return self.env["hlv.vendor.quote.line"]._hlv_vat_options(self.env.company)

    @api.depends("order_line_id.price_unit", "order_line_id.taxes_id")
    def _compute_current_price_incl(self):
        for wizard in self:
            line = wizard.order_line_id
            wizard.current_tax_rate = tax_rate_of(line)
            wizard.current_price_incl = price_incl_vat(line.price_unit, wizard.current_tax_rate)

    @api.depends("order_line_id")
    def _compute_prefill(self):
        options = dict(self._selection_vat())
        for wizard in self:
            line = wizard.order_line_id
            wizard.suggested_price_incl = price_incl_vat(line.price_unit, tax_rate_of(line))
            wizard.suggested_qty = line.product_qty
            code = vat_code_of(line) if line else ""
            # Mức công ty không còn khai thuế mua thì không có trong ô chọn — để trống (= giữ VAT trên đơn).
            wizard.suggested_vat = code if code in options else False

    def action_submit(self):
        self.ensure_one()
        self.env["hlv.po.price.proposal"]._buyer_propose(
            self.order_line_id, self.suggested_price_incl, self.note, self.suggested_qty, self.suggested_product_id,
            self.suggested_vat or "")
        return {"type": "ir.actions.act_window_close"}
