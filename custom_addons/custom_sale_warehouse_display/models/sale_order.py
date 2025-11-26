# -*- coding: utf-8 -*-
from odoo import models, fields, api

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
            # Chỉ lấy phiếu kho không bị hủy
            valid_pickings = order.picking_ids.filtered(lambda p: p.state != 'cancel')
            for picking in valid_pickings:
                if picking.location_id and picking.location_id.warehouse_id:
                    warehouse_codes.add(picking.location_id.warehouse_id.code)
            
            if warehouse_codes:
                # Sắp xếp để hiển thị nhất quán (VD: KBC, TSN)
                order.effective_warehouse_names = ", ".join(sorted(list(warehouse_codes)))
            else:
                # Fallback về kho mặc định của đơn hàng nếu chưa có phiếu xuất
                order.effective_warehouse_names = order.warehouse_id.code if order.warehouse_id else ""

    def action_view_order_lines_popup(self):
        self.ensure_one()
        return {
            'name': f'Chi tiết sản phẩm - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.line',
            'view_mode': 'list', # Odoo 18 python vẫn gọi là view_mode='list' (hoặc tree vẫn hiểu)
            'domain': [('order_id', '=', self.id)],
            'target': 'new',
            'context': {'create': False, 'edit': False}
        }