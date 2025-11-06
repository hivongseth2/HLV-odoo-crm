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
        Tính toán domain cho picking_type_id dựa trên nguồn gốc của picking
        Logic ưu tiên:
        1. Nếu có sale_id -> Chỉ hiển thị: Lấy hàng, Gói, Lệnh giao hàng
        2. Nếu có purchase_id -> Chỉ hiển thị: Phiếu nhập kho
        3. Nếu picking_type_code = 'internal' -> Chỉ hiển thị: Lệnh chuyển hàng nội bộ
        4. Nếu origin chứa 'S' (Sale) và code = 'outgoing' -> Sale related
        5. Nếu origin chứa 'P' (Purchase) và code = 'incoming' -> Purchase related
        6. Các trường hợp khác -> Hiển thị tất cả
        """
        for picking in self:
            domain = []
            picking_types = self.env['stock.picking.type']
            
            # 1. Kiểm tra nguồn gốc từ Sale Order
            if picking.sale_id:
                # Lấy hàng, Gói, Lệnh giao hàng
                domain = [
                    '|', '|', '|',
                    ('name', 'ilike', 'Lấy hàng'),
                    ('name', 'ilike', 'Gói'),
                    ('name', 'ilike', 'Lệnh giao hàng'),
                    ('name', 'ilike', 'Cross-dock'),
                    ('code', '=', 'outgoing')
                ]
            
            # 2. Kiểm tra nguồn gốc từ Purchase Order
            elif picking.purchase_id:
                # Phiếu nhập kho
                domain = [
                    '|',
                    ('name', 'ilike', 'Phiếu nhập kho'),
                    ('code', '=', 'incoming')
                ]
            
            # 3. Kiểm tra nếu là chuyển hàng nội bộ
            elif picking.picking_type_code == 'internal' or (
                picking.picking_type_id and picking.picking_type_id.code == 'internal'
            ):
                # Lệnh chuyển hàng nội bộ
                domain = [
                    '|',
                    ('name', 'ilike', 'Lệnh chuyển hàng nội bộ'),
                    ('code', '=', 'internal')
                ]
            
            # 4. Kiểm tra origin để xác định nguồn gốc
            elif picking.origin:
                origin_upper = picking.origin.upper()
                # Kiểm tra nếu origin bắt đầu bằng 'S' (Sale Order)
                if origin_upper.startswith('S') or 'SO' in origin_upper:
                    domain = [
                        '|', '|', '|',
                        ('name', 'ilike', 'Lấy hàng'),
                        ('name', 'ilike', 'Gói'),
                        ('name', 'ilike', 'Lệnh giao hàng'),
                        ('name', 'ilike', 'Cross-dock'),
                        ('code', '=', 'outgoing')
                    ]
                # Kiểm tra nếu origin bắt đầu bằng 'P' (Purchase Order)
                elif origin_upper.startswith('P') or 'PO' in origin_upper:
                    domain = [
                        '|',
                        ('name', 'ilike', 'Phiếu nhập kho'),
                        ('code', '=', 'incoming')
                    ]
            
            # 5. Kiểm tra theo picking_type_code hiện tại
            elif picking.picking_type_id:
                current_code = picking.picking_type_id.code
                if current_code == 'outgoing':
                    domain = [
                        '|', '|', '|',
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
                elif current_code == 'internal':
                    domain = [
                        '|',
                        ('name', 'ilike', 'Lệnh chuyển hàng nội bộ'),
                        ('code', '=', 'internal')
                    ]
            
            # Lấy danh sách picking types phù hợp
            if domain:
                picking_types = self.env['stock.picking.type'].search(domain)
            else:
                # Nếu không xác định được, cho phép tất cả
                picking_types = self.env['stock.picking.type'].search([])
            
            picking.picking_type_domain_ids = picking_types

    @api.onchange('sale_id', 'purchase_id')
    def _onchange_origin_document(self):
        """
        Khi thay đổi sale_id hoặc purchase_id, tính toán lại domain
        """
        self._compute_picking_type_domain()
