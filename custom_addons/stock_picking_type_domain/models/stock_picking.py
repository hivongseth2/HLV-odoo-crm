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

    @api.depends(
        'sale_id',
        'purchase_id',
        'picking_type_id',
        'picking_type_code',
        'origin',
        'return_id',
        'move_ids.origin_returned_move_id',
    )
    def _compute_picking_type_domain(self):
        """
        Tính toán domain cho picking_type_id dựa trên nguồn gốc của picking
        Logic ưu tiên:
        1. Nếu là phiếu trả -> Lọc theo chiều hoạt động của phiếu trả
        2. Nếu có sale_id -> Chỉ hiển thị: Lấy hàng, Gói, Lệnh giao hàng
        3. Nếu có purchase_id -> Chỉ hiển thị: Phiếu nhập kho
        4. Nếu picking_type_code = 'internal' -> Chỉ hiển thị: Lệnh chuyển hàng nội bộ
        5. Nếu origin chứa 'S' (Sale) -> Sale related
        6. Nếu origin chứa 'P' (Purchase) -> Purchase related
        7. Các trường hợp khác -> Hiển thị tất cả
        """
        for picking in self:
            domain = []
            picking_types = self.env['stock.picking.type']

            # Phiếu trả vẫn kế thừa sale_id/purchase_id từ chứng từ gốc,
            # nhưng chiều hoạt động đã đảo ngược. Vì vậy phải xử lý
            # phiếu trả trước nhánh Sale/Purchase. Kiểm tra thêm chiều
            # ngược Sale/incoming hoặc Purchase/outgoing để hỗ trợ dữ liệu cũ
            # không còn liên kết return_id/move trả.
            current_code = picking.picking_type_id.code if picking.picking_type_id else False
            has_reversed_document_flow = bool(
                (picking.sale_id and current_code == 'incoming')
                or (picking.purchase_id and current_code == 'outgoing')
            )
            is_return = bool(
                picking.return_id
                or picking.move_ids.filtered('origin_returned_move_id')
                or has_reversed_document_flow
            )
            if is_return and picking.picking_type_id:
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
                elif current_code == 'internal':
                    domain = [
                        '|',
                        ('name', 'ilike', 'Lệnh chuyển hàng nội bộ'),
                        ('code', '=', 'internal')
                    ]

            # 2. Kiểm tra nguồn gốc từ Sale Order
            elif picking.sale_id:
                # Lấy hàng, Gói, Lệnh giao hàng, Cross-dock
                domain = [
                    '|', '|', '|', '|',
                    ('name', 'ilike', 'Lấy hàng'),
                    ('name', 'ilike', 'Gói'),
                    ('name', 'ilike', 'Lệnh giao hàng'),
                    ('name', 'ilike', 'Cross-dock'),
                    ('code', '=', 'outgoing')
                ]
            
            # 3. Kiểm tra nguồn gốc từ Purchase Order
            elif picking.purchase_id:
                # Phiếu nhập kho
                domain = [
                    '|',
                    ('name', 'ilike', 'Phiếu nhập kho'),
                    ('code', '=', 'incoming')
                ]
            
            # 4. Kiểm tra nếu là chuyển hàng nội bộ
            elif picking.picking_type_code == 'internal' or (
                picking.picking_type_id and picking.picking_type_id.code == 'internal'
            ):
                # Lệnh chuyển hàng nội bộ
                domain = [
                    '|',
                    ('name', 'ilike', 'Lệnh chuyển hàng nội bộ'),
                    ('code', '=', 'internal')
                ]
            
            # 5. Kiểm tra origin để xác định nguồn gốc
            elif picking.origin:
                origin_upper = picking.origin.upper()
                # Kiểm tra nếu origin bắt đầu bằng 'S' (Sale Order)
                if origin_upper.startswith('S') or 'SO' in origin_upper:
                    domain = [
                        '|', '|', '|', '|',
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
            
            # 6. Kiểm tra theo picking_type_code hiện tại
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

            # Không để giá trị đang lưu bị trắng nếu picking type cũ
            # không còn khớp quy tắc tên/code hiện tại.
            picking_types |= picking.picking_type_id
            picking.picking_type_domain_ids = picking_types

    @api.onchange('sale_id', 'purchase_id')
    def _onchange_origin_document(self):
        """
        Khi thay đổi sale_id hoặc purchase_id, tính toán lại domain
        """
        self._compute_picking_type_domain()
