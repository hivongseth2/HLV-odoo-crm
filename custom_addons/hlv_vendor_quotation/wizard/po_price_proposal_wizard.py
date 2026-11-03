# -*- coding: utf-8 -*-
"""Hộp "Đề xuất giá" trên dòng đơn mua: thu mua ghi giá gợi ý (sau VAT) + lý do — không sửa thẳng đơn giá
(dòng lên từ hỏi giá bị khoá, xem models/purchase_order_line_price.py)."""

from odoo import api, fields, models

from ..models.purchase_order_revision import tax_rate_of
from ..models.vendor_quote_utils import price_incl_vat


class PurchaseOrderPriceProposalWizard(models.TransientModel):
    _name = "hlv.po.price.proposal.wizard"
    _description = "Thu mua đề xuất giá dòng đơn mua"

    order_line_id = fields.Many2one("purchase.order.line", string="Dòng đơn mua", required=True, readonly=True)
    product_id = fields.Many2one(related="order_line_id.product_id", string="Sản phẩm")
    vendor_id = fields.Many2one(related="order_line_id.partner_id", string="Nhà cung cấp")
    current_price_incl = fields.Float(string="Giá trên đơn (sau VAT)", digits="Product Price",
                                      compute="_compute_current_price_incl")
    suggested_price_incl = fields.Float(string="Giá gợi ý (sau VAT)", digits="Product Price",
                                        help="Giá thu mua mong muốn — sale dùng để thương lượng khi hỏi lại NCC. "
                                             "Để 0 nếu chỉ cần NCC báo lại giá.")
    note = fields.Text(string="Lý do", required=True,
                       help="VD: NCC khác báo rẻ hơn, giá thị trường đã giảm… — sale đọc trên trang Hỏi giá NCC.")

    @api.depends("order_line_id.price_unit", "order_line_id.taxes_id")
    def _compute_current_price_incl(self):
        for wizard in self:
            line = wizard.order_line_id
            wizard.current_price_incl = price_incl_vat(line.price_unit, tax_rate_of(line))

    def action_submit(self):
        self.ensure_one()
        self.env["hlv.po.price.proposal"]._buyer_propose(self.order_line_id, self.suggested_price_incl, self.note)
        return {"type": "ir.actions.act_window_close"}
