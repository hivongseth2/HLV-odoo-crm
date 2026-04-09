# -*- coding: utf-8 -*-
from odoo import models, fields, api


class StockPickingTypeBarcode(models.Model):
    """Add barcode scanning configuration per operation type."""
    _inherit = 'stock.picking.type'

    barcode_scan_source = fields.Selection([
        ('no', 'Không quét'),
        ('per_product', 'Quét theo từng sản phẩm'),
        ('per_group', 'Quét theo nhóm sản phẩm'),
    ], string='Quét vị trí nguồn', default='no',
        help='Cấu hình quét vị trí nguồn khi xử lý phiếu bằng barcode')

    barcode_scan_dest = fields.Selection([
        ('no', 'Không quét'),
        ('per_product', 'Quét theo từng sản phẩm'),
        ('per_group', 'Quét theo nhóm sản phẩm'),
    ], string='Quét vị trí đích', default='no',
        help='Cấu hình quét vị trí đích khi xử lý phiếu bằng barcode')

    barcode_require_product_scan = fields.Boolean(
        string='Yêu cầu quét sản phẩm', default=True,
        help='Nếu tắt, nhân viên không cần quét mã sản phẩm, chỉ cần xác nhận số lượng')
