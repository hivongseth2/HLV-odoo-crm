# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools.float_utils import float_round

class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    ignore_forecast = fields.Boolean(
        string="Ignore Forecast",
        help="Nếu bật, số lượng đặt hàng chỉ bù đến tồn tối thiểu dựa trên tồn thực tế "
             "(qty_available), bỏ qua Dự báo.",
        default=True,
    )

    def _quantity_to_order(self, product, qty_available, qty_forecast, **kwargs):
        self.ensure_one()
        if self.ignore_forecast:
            on_hand = product.qty_available
            need = max(0.0, self.product_min_qty - on_hand)

            need_uom = self.product_uom._compute_quantity(
                need, product.uom_id, rounding_method="HALF-UP"
            )
            need_uom = float_round(need_uom, precision_rounding=self.product_uom.rounding)
            return need_uom

        return super()._quantity_to_order(product, qty_available, qty_forecast, **kwargs)
