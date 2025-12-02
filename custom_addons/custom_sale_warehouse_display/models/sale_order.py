# -*- coding: utf-8 -*-
from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # 1. BIẾN CŨ (Giữ nguyên tên để không lỗi): Dùng làm "Kho dự kiến"
    effective_warehouse_names = fields.Char(
        string="Kho dự kiến", 
        compute='_compute_warehouse_info',
        store=True
    )

    # 2. BIẾN MỚI: Dùng làm "Kho đã xuất"
    warehouse_done_names = fields.Char(
        string="Kho đã xuất",
        compute='_compute_warehouse_info',
        store=True
    )

    # 3. Trường alias để tương thích ngược với view cũ (nếu có cache)
    warehouse_plan_names = fields.Char(
        string="Kho dự kiến (alias)",
        compute='_compute_warehouse_plan_alias',
        store=False
    )

    @api.depends('effective_warehouse_names')
    def _compute_warehouse_plan_alias(self):
        """Alias field để tương thích ngược"""
        for order in self:
            order.warehouse_plan_names = order.effective_warehouse_names

    @api.depends('picking_ids', 'picking_ids.state', 'picking_ids.location_id', 'picking_ids.date_done')
    def _compute_warehouse_info(self):
        for order in self:
            plan_codes = set()
            done_codes = set()
            
            # Lấy các phiếu không hủy
            valid_pickings = order.picking_ids.filtered(lambda p: p.state != 'cancel')
            
            for picking in valid_pickings:
                if picking.location_id and picking.location_id.warehouse_id:
                    code = picking.location_id.warehouse_id.code
                    
                    # Logic cũ: Tất cả các kho có trong phiếu -> Là Kế hoạch
                    plan_codes.add(code)
                    
                    # Logic mới: Chỉ phiếu đã xong -> Là Thực tế
                    if picking.state == 'done':
                        done_codes.add(code)
            
            # Gán dữ liệu
            order.effective_warehouse_names = ", ".join(sorted(list(plan_codes))) if plan_codes else ""
            order.warehouse_done_names = ", ".join(sorted(list(done_codes))) if done_codes else ""

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