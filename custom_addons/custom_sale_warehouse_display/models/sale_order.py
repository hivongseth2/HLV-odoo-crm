# -*- coding: utf-8 -*-
from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    effective_warehouse_names = fields.Char(
        string="Kho đã xuất", # Đổi tên cho sát nghĩa
        compute='_compute_effective_warehouse_names',
        store=True
    )

    @api.depends('picking_ids', 'picking_ids.state', 'picking_ids.location_id', 'picking_ids.date_done')
    def _compute_effective_warehouse_names(self):
        for order in self:
            warehouse_codes = set()
            # CHỈ LẤY PHIẾU ĐÃ HOÀN THÀNH (state == 'done')
            # Điều này giúp loại bỏ kho TSN nếu kho đó chưa xuất hàng
            done_pickings = order.picking_ids.filtered(lambda p: p.state == 'done')
            
            for picking in done_pickings:
                if picking.location_id and picking.location_id.warehouse_id:
                    warehouse_codes.add(picking.location_id.warehouse_id.code)
            
            if warehouse_codes:
                order.effective_warehouse_names = ", ".join(sorted(list(warehouse_codes)))
            else:
                # Nếu chưa có phiếu nào xong, để trống hoặc hiện "Chưa xuất"
                order.effective_warehouse_names = "" 
                # Hoặc nếu muốn hiện kho dự kiến thì dùng dòng dưới:
                # order.effective_warehouse_names = f"({order.warehouse_id.code} - Chờ)" if order.warehouse_id else ""
    
    def action_view_order_lines_popup(self):
        self.ensure_one()
        return {
            'name': f'Chi tiết SP - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.line',
            'view_mode': 'list',
            'domain': [('order_id', '=', self.id)],
            'target': 'new',
            'context': {'create': False, 'edit': False}
        }