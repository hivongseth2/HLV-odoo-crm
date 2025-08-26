# -*- coding: utf-8 -*-
from math import ceil
from odoo import api, fields, models
from odoo.tools.float_utils import float_round

class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    ignore_forecast = fields.Boolean(
        string="Ignore Forecast",
        help="Nếu bật, số lượng đặt hàng chỉ bù đến tồn tối thiểu dựa trên tồn thực tế (qty_available), bỏ qua Dự báo.",
        default=True,
    )

    def _compute_ignore_forecast_qty(self, product, min_qty, on_hand, qty_multiple):
        """Bù đến min dựa trên tồn thực tế + tôn trọng bội số và UoM."""
        need = max(0.0, min_qty - on_hand)
        # bội số đặt hàng (nếu có) – làm tròn lên theo bội số
        if qty_multiple:
            need = ceil(need / qty_multiple) * qty_multiple
        # làm tròn theo UoM của sản phẩm
        need = float_round(need, precision_rounding=product.uom_id.rounding)
        return need

    # ① Dùng cho scheduler / replenishment
    def _quantity_to_order(self, product, qty_available, qty_forecast, **kwargs):
        self.ensure_one()
        if self.ignore_forecast:
            return self._compute_ignore_forecast_qty(
                product=product,
                min_qty=self.product_min_qty,
                on_hand=product.qty_available,
                qty_multiple=self.qty_multiple,
            )
        return super()._quantity_to_order(product, qty_available, qty_forecast, **kwargs)

    # ② Dùng cho hiển thị cột "Cần đặt hàng" (list) & nút Order
    @api.depends(
        'ignore_forecast',       # thêm để đổi checkbox là tự recompute
        'product_min_qty', 'product_max_qty',
        'qty_on_hand', 'qty_forecast',
        'qty_multiple', 'trigger'
    )
    def _compute_qty_to_order(self):
        # tính mặc định trước (để trường hợp không tick thì theo Odoo)
        super()._compute_qty_to_order()
        for op in self:
            # chỉ can thiệp khi auto (để không ghi đè số nhập tay)
            if op.ignore_forecast and op.trigger == 'auto':
                op.qty_to_order = op._compute_ignore_forecast_qty(
                    product=op.product_id,
                    min_qty=op.product_min_qty,
                    on_hand=op.qty_on_hand,       # số thực tế đang hiển thị ở list
                    qty_multiple=op.qty_multiple,
                )
