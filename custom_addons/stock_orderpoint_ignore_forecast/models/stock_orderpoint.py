# -*- coding: utf-8 -*-
from math import ceil
from odoo import api, fields, models
from odoo.tools.float_utils import float_round

class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    ignore_forecast = fields.Boolean(
        string="Ignore Forecast",
        help="Nếu bật, chỉ bù đến tồn tối thiểu theo tồn thực tế (bỏ Forecast).",
        default=True,
    )

    @api.depends(
        'ignore_forecast', 'trigger',
        'product_min_qty', 'product_max_qty',
        'qty_on_hand', 'qty_forecast',
        'qty_multiple', 'product_id.uom_id'
    )
    def _compute_qty_to_order(self):
        for op in self:
            # Nếu manual thì để người dùng nhập tay, không đụng vào
            if op.trigger != 'auto':
                continue

            # Công thức theo yêu cầu khi tick Ignore Forecast
            if op.ignore_forecast:
                base = op.product_min_qty - (op.qty_on_hand or 0.0)
            else:
                # Công thức gần tương đương mặc định Odoo (đạt Max theo Forecast)
                base = op.product_max_qty - (op.qty_forecast or 0.0)

            need = max(0.0, base)

            # Áp dụng bội số đặt hàng (nếu có)
            if op.qty_multiple:
                need = ceil(need / op.qty_multiple) * op.qty_multiple

            # Làm tròn theo UoM của sản phẩm
            rounding = (op.product_id.uom_id and op.product_id.uom_id.rounding) or 1.0
            op.qty_to_order = float_round(need, precision_rounding=rounding)

    # Scheduler / replenish vẫn hoạt động đúng với Ignore Forecast
    def _quantity_to_order(self, product, qty_available, qty_forecast, **kwargs):
        self.ensure_one()
        if self.ignore_forecast and self.trigger == 'auto':
            on_hand = product.qty_available
            base = self.product_min_qty - (on_hand or 0.0)
            need = max(0.0, base)
            if self.qty_multiple:
                need = ceil(need / self.qty_multiple) * self.qty_multiple
            rounding = (product.uom_id and product.uom_id.rounding) or 1.0
            return float_round(need, precision_rounding=rounding)
        # Ngược lại giữ hành vi gốc
        return super()._quantity_to_order(product, qty_available, qty_forecast, **kwargs)
