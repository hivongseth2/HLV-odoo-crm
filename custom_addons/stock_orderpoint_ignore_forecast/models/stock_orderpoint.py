# -*- coding: utf-8 -*-
from math import ceil
from odoo import api, fields, models
from odoo.tools.float_utils import float_round

class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    qty_to_order_min_only = fields.Float(
        string="Cần đặt (Min)",
        compute="_compute_qty_to_order_min_only",
        digits="Product Unit of Measure",
        store=False,
        help="max(0, Min - On Hand), áp dụng qty_multiple và làm tròn theo UoM. Bỏ Forecast."
    )

    @api.depends('product_min_qty', 'qty_on_hand', 'qty_multiple', 'product_id.uom_id')
    def _compute_qty_to_order_min_only(self):
        for op in self:
            need = max(0.0, (op.product_min_qty or 0.0) - (op.qty_on_hand or 0.0))
            if op.qty_multiple:
                need = ceil(need / (op.qty_multiple or 1.0)) * op.qty_multiple
            rounding = (op.product_id.uom_id and op.product_id.uom_id.rounding) or 1.0
            op.qty_to_order_min_only = float_round(need, precision_rounding=rounding)

    def action_replenish_min_only(self):
        for op in self:
            if op.qty_to_order_min_only and op.qty_to_order_min_only > 0:
                op.qty_to_order_manual = op.qty_to_order_min_only
        return self.action_replenish()
