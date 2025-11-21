# -*- coding: utf-8 -*-

from odoo import models, fields, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    picking_type_domain_ids = fields.Many2many(
        'stock.picking.type',
        compute='_compute_picking_type_domain',
        string='Allowed Picking Types',
        help='Domain tính toán để giới hạn các loại hoạt động cho phép'
    )

    @api.depends('sale_id', 'purchase_id', 'picking_type_id', 'picking_type_code', 'origin')
    def _compute_picking_type_domain(self):
        """
        Tính toán domain cho picking_type_id.
        Logic sửa đổi: Kiểm tra nguồn gốc (Sale/Purchase) TRƯỚC, sau đó mới kiểm tra mã nội bộ (Internal).
        """
        for picking in self:
            domain = []
            picking_types = self.env['stock.picking.type']
            
            # Lấy thông tin origin và chuẩn hóa chữ hoa để so sánh
            origin_upper = picking.origin.upper() if picking.origin else ''
            
            # --- ƯU TIÊN 1: KIỂM TRA NGUỒN GỐC TỪ BÁN HÀNG (SALE) ---
            # Gộp điều kiện: Có Sale ID HOẶC Origin bắt đầu bằng S/SO/DH (nếu có) HOẶC type là outgoing
            if picking.sale_id or \
               origin_upper.startswith('S') or 'SO' in origin_upper or origin_upper.startswith('DH') or \
               (picking.picking_type_code == 'outgoing' and not picking.purchase_id):
                
                # Hiển thị: Lấy hàng, Gói, Lệnh giao hàng, Cross-dock
                domain = [
                    '|', '|', '|', '|',
                    ('name', 'ilike', 'Lấy hàng'),
                    ('name', 'ilike', 'Gói'),
                    ('name', 'ilike', 'Lệnh giao hàng'),
                    ('name', 'ilike', 'Cross-dock'),
                    ('code', '=', 'outgoing')
                ]

            # --- ƯU TIÊN 2: KIỂM TRA NGUỒN GỐC TỪ MUA HÀNG (PURCHASE) ---
            elif picking.purchase_id or \
                 origin_upper.startswith('P') or 'PO' in origin_upper or \
                 (picking.picking_type_code == 'incoming' and not picking.sale_id):
                
                # Hiển thị: Phiếu nhập kho
                domain = [
                    '|',
                    ('name', 'ilike', 'Phiếu nhập kho'),
                    ('code', '=', 'incoming')
                ]

            # --- ƯU TIÊN 3: CHUYỂN NỘI BỘ (INTERNAL) ---
            # Chỉ chạy vào đây nếu KHÔNG PHẢI là Sale hoặc Purchase ở trên
            elif picking.picking_type_code == 'internal' or (
                picking.picking_type_id and picking.picking_type_id.code == 'internal'
            ):
                domain = [
                    '|',
                    ('name', 'ilike', 'Lệnh chuyển hàng nội bộ'),
                    ('code', '=', 'internal')
                ]
            
            # --- ƯU TIÊN 4: CÁC TRƯỜNG HỢP CÒN LẠI (FALLBACK) ---
            elif picking.picking_type_id:
                current_code = picking.picking_type_id.code
                if current_code == 'outgoing':
                    domain = [
                        '|', '|', '|', '|',
                        ('name', 'ilike', 'Lấy hàng'),
                        ('name', 'ilike', 'Gói'),
                        ('name', 'ilike', 'Lệnh giao hàng'),
                        ('name', 'ilike', 'Cross-dock'),
                        ('code', '=', 'outgoing')
                    ]
                elif current_code == 'incoming':
                    domain = [
                        '|',
                        ('name', 'ilike', 'Phiếu nhập kho'),
                        ('code', '=', 'incoming')
                    ]

            # Tìm kiếm Picking Type theo domain đã xác định
            if domain:
                picking_types = self.env['stock.picking.type'].search(domain)
            else:
                # Nếu không thỏa mãn điều kiện nào, cho phép hiển thị tất cả (hoặc rỗng tùy logic của bạn)
                picking_types = self.env['stock.picking.type'].search([])
            
            picking.picking_type_domain_ids = picking_types

    @api.onchange('sale_id', 'purchase_id', 'origin')
    def _onchange_origin_document(self):
        """
        Trigger tính toán lại khi thay đổi nguồn gốc
        """
        self._compute_picking_type_domain()