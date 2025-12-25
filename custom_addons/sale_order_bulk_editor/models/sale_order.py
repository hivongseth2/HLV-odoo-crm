# -*- coding: utf-8 -*-
from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_view_order_detail(self):
        """
        Mở form view chi tiết của đơn hàng.
        Dùng khi list view đang ở chế độ editable và muốn xem chi tiết đơn.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.id,
            'view_mode': 'form',
            'view_type': 'form',
            'target': 'current',
        }
