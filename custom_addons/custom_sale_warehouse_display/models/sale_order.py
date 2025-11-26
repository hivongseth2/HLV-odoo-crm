# -*- coding: utf-8 -*-
from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Định nghĩa field mới
    effective_warehouse_names = fields.Char(
        string="Kho hàng",
        compute='_compute_effective_warehouse_names',
        store=True, # Lưu vào database để search/filter nhanh và hỗ trợ hiển thị dữ liệu cũ
        help="Hiển thị mã kho dựa trên các phiếu xuất kho thực tế."
    )

    @api.depends('picking_ids', 'picking_ids.state', 'picking_ids.location_id')
    def _compute_effective_warehouse_names(self):
        for order in self:
            warehouse_codes = set()
            
            # Lấy các phiếu kho liên quan (trừ phiếu đã hủy nếu muốn)
            # Ở đây tôi lấy tất cả phiếu kho ngoại trừ phiếu Hủy (Cancel)
            valid_pickings = order.picking_ids.filtered(lambda p: p.state != 'cancel')
            
            for picking in valid_pickings:
                # Lấy Warehouse từ địa điểm nguồn (Source Location) của phiếu kho
                if picking.location_id and picking.location_id.warehouse_id:
                    # Lấy Mã kho (Code) ví dụ: TSN, KBC. Nếu muốn lấy tên đầy đủ thì dùng .name
                    warehouse_codes.add(picking.location_id.warehouse_id.code)
            
            # Nếu có phiếu kho thì join lại, nếu không thì để trống 
            # (hoặc lấy kho mặc định của SO nếu bạn muốn: order.warehouse_id.code)
            if warehouse_codes:
                # Sắp xếp để hiển thị đẹp hơn (VD: KBC, TSN)
                order.effective_warehouse_names = ", ".join(sorted(list(warehouse_codes)))
            else:
                # Fallback: Nếu chưa có phiếu kho, hiển thị kho dự kiến trên đơn hàng
                order.effective_warehouse_names = order.warehouse_id.code if order.warehouse_id else ""