# -*- coding: utf-8 -*-
from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # 1. Cột hiển thị KẾ HOẠCH (Phiếu này sẽ lấy ở những kho nào?)
    warehouse_plan_names = fields.Char(
        string="Kho dự kiến",
        compute='_compute_warehouse_info',
        store=True,
        help="Hiển thị tất cả các kho có trong kế hoạch giao hàng (chưa hủy)"
    )

    # 2. Cột hiển thị THỰC TẾ (Kho nào ĐÃ xuất xong?)
    warehouse_done_names = fields.Char(
        string="Kho đã xuất",
        compute='_compute_warehouse_info',
        store=True,
        help="Chỉ hiển thị các kho đã hoàn thành phiếu xuất"
    )
    
    effective_warehouse_names = fields.Char(related='warehouse_done_names', string="Kho cũ (Sắp xóa)")

    @api.depends('picking_ids', 'picking_ids.state', 'picking_ids.location_id', 'picking_ids.date_done')
    def _compute_warehouse_info(self):
        for order in self:
            plan_codes = set()
            done_codes = set()
            
            # Lấy tất cả phiếu kho không bị hủy
            valid_pickings = order.picking_ids.filtered(lambda p: p.state != 'cancel')
            
            for picking in valid_pickings:
                if picking.location_id and picking.location_id.warehouse_id:
                    code = picking.location_id.warehouse_id.code
                    
                    # Logic 1: Luôn thêm vào danh sách Kế hoạch
                    plan_codes.add(code)
                    
                    # Logic 2: Chỉ thêm vào danh sách Đã xuất nếu phiếu đã Done
                    if picking.state == 'done':
                        done_codes.add(code)
            
            # Gán dữ liệu (Sắp xếp A-Z cho đẹp)
            order.warehouse_plan_names = ", ".join(sorted(list(plan_codes))) if plan_codes else ""
            order.warehouse_done_names = ", ".join(sorted(list(done_codes))) if done_codes else ""

    # Hàm mở popup xem sản phẩm (giữ nguyên)
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