# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.tools.float_utils import float_round

class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    ignore_forecast = fields.Boolean(
        string="Ignore Forecast",
        help="Nếu bật, số lượng đặt hàng chỉ bù đến tồn tối thiểu dựa trên tồn thực tế (qty_available), bỏ qua Dự báo.",
        default=True,
    )

    def _compute_ignore_forecast_qty(self, product):
        """Bù đến min dựa trên tồn thực tế, làm tròn theo UoM của sản phẩm."""
        on_hand = product.qty_available
        need = max(0.0, self.product_min_qty - on_hand)
        # Trên Odoo 16, orderpoint hiển thị product_uom_name, dùng rounding của product.uom_id
        need = float_round(need, precision_rounding=product.uom_id.rounding)
        return need

    # Trường hợp scheduler gọi _quantity_to_order(...)
    def _quantity_to_order(self, product, qty_available, qty_forecast, **kwargs):
        self.ensure_one()
        if self.ignore_forecast:
            return self._compute_ignore_forecast_qty(product)
        return super()._quantity_to_order(product, qty_available, qty_forecast, **kwargs)

    # Trường hợp build khác gọi _get_orderpoint_procurement_qty(...)
    def _get_orderpoint_procurement_qty(self):
        self.ensure_one()
        if self.ignore_forecast:
            return self._compute_ignore_forecast_qty(self.product_id)
        return super()._get_orderpoint_procurement_qty()
