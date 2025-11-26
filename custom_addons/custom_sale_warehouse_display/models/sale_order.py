# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, time

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    effective_warehouse_names = fields.Char(
        string="Kho hàng",
        compute='_compute_effective_warehouse_names',
        store=True
    )

    @api.depends('picking_ids', 'picking_ids.state', 'picking_ids.location_id')
    def _compute_effective_warehouse_names(self):
        for order in self:
            warehouse_codes = set()
            valid_pickings = order.picking_ids.filtered(lambda p: p.state != 'cancel')
            for picking in valid_pickings:
                if picking.location_id and picking.location_id.warehouse_id:
                    warehouse_codes.add(picking.location_id.warehouse_id.code)
            
            if warehouse_codes:
                order.effective_warehouse_names = ", ".join(sorted(list(warehouse_codes)))
            else:
                order.effective_warehouse_names = order.warehouse_id.code if order.warehouse_id else ""

    # --- HÀM MỚI THÊM: Action cho nút xem sản phẩm ---
    def action_view_order_lines_popup(self):
        self.ensure_one()
        return {
            'name': f'Sản phẩm của {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.line',
            'view_mode': 'list', # Chỉ hiện dạng danh sách
            'domain': [('order_id', '=', self.id)], # Lọc theo đơn hàng hiện tại
            'target': 'new', # Mở dạng popup
            'context': {'create': False, 'edit': False} # Chỉ xem, không cho sửa nhanh để tránh lỗi
        }