# -*- coding: utf-8 -*-
from math import ceil
from odoo import api, fields, models
from odoo.tools.float_utils import float_round

class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    # CỘT MỚI: chỉ bù tới Min dựa trên tồn thực tế (bỏ Forecast)
    qty_to_order_min_only = fields.Float(
        string="Cần đặt (Min)",
        compute="_compute_qty_to_order_min_only",
        digits="Product Unit of Measure",
        help="= max(0, Tồn tối thiểu − Hiện có), áp dụng bội số (qty_multiple) và làm tròn theo UoM. "
             "Không sử dụng Dự báo (Forecast).",
        store=False,
    )

    @api.depends('product_min_qty', 'qty_on_hand', 'qty_multiple', 'product_id.uom_id')
    def _compute_qty_to_order_min_only(self):
        for op in self:
            on_hand = op.qty_on_hand or 0.0
            min_qty = op.product_min_qty or 0.0
            need = max(0.0, min_qty - on_hand)
            # bội số đặt hàng
            if op.qty_multiple:
                need = ceil(need / (op.qty_multiple or 1.0)) * op.qty_multiple
            # làm tròn theo UoM
            rounding = (op.product_id.uom_id and op.product_id.uom_id.rounding) or 1.0
            op.qty_to_order_min_only = float_round(need, precision_rounding=rounding)

    def action_replenish_min_only(self):
        """
        Đặt hàng theo số 'Cần đặt (Min)' bằng qty_to_order_manual rồi gọi replenish như thường.
        KHÔNG thay đổi cột 'Cần đặt hàng' mặc định (vẫn theo Forecast).
        """
        for op in self:
            if op.qty_to_order_min_only and op.qty_to_order_min_only > 0:
                op.qty_to_order_manual = op.qty_to_order_min_only
        return self.action_replenish()
