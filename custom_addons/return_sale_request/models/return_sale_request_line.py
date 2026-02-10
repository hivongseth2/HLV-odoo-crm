# -*- coding: utf-8 -*-
"""
Model chi tiết: return.sale.request.line
"""
from odoo import api, fields, models


class ReturnSaleRequestLine(models.Model):
    _name = "return.sale.request.line"
    _description = "Chi tiết đề nghị trả hàng"
    _order = "id"

    request_id = fields.Many2one(
        comodel_name="return.sale.request",
        string="Đề nghị trả hàng",
        required=True,
        ondelete="cascade",
        index=True,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Sản phẩm",
        required=True,
    )
    product_qty = fields.Float(
        string="Số lượng",
        required=True,
        default=1.0,
        digits="Product Unit of Measure",
    )
    return_to_vendor_qty = fields.Float(
        string="Số SL trả lại NCC",
        default=0.0,
        digits="Product Unit of Measure",
        help="Nếu > 0 thì hệ thống sẽ tạo phiếu xuất trả NCC với số lượng này.",
    )
    product_uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Đơn vị",
        related="product_id.uom_id",
        store=True,
    )
    unit_price = fields.Float(
        string="Đơn giá",
        digits="Product Price",
    )
    subtotal = fields.Monetary(
        string="Thành tiền (trước thuế)",
        store=True,
        currency_field="currency_id",
    )
    line_total = fields.Monetary(
        string="Tổng tiền (sau thuế)",
        store=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        related="request_id.currency_id",
        readonly=True,
    )
    note = fields.Char(string="Ghi chú")

    # Related fields
    state = fields.Selection(
        related="request_id.state",
        store=True,
    )

    @api.onchange("product_qty", "unit_price")
    def _onchange_qty_price(self):
        """Recalculate subtotal and line_total when qty/price changes in UI"""
        if not self.subtotal and self.product_qty and self.unit_price:
            self.subtotal = self.product_qty * self.unit_price
            self.line_total = self.subtotal

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id
            if not self.unit_price:
                self.unit_price = self.product_id.lst_price or 0.0
