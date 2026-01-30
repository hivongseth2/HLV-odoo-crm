# -*- coding: utf-8 -*-
from odoo import models, fields, api


class InventoryScanLine(models.Model):
    _name = 'inventory.scan.line'
    _description = 'Inventory Scan Line - Dòng sản phẩm đã quét'
    _order = 'create_date desc'

    session_id = fields.Many2one(
        'inventory.scan.session',
        string='Session',
        required=True,
        ondelete='cascade',
        index=True
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        index=True
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Location',
        index=True
    )
    
    # Số lượng đã quét (tổng cộng cho sản phẩm này trong session)
    scanned_qty = fields.Float(
        string='Số lượng đã quét',
        default=0.0,
        required=True,
        help='Tổng số lượng đã quét cho sản phẩm này'
    )
    
    # Số lượng lý thuyết (từ stock.quant tại thời điểm bắt đầu)
    theoretical_qty = fields.Float(
        string='Tồn kho lý thuyết',
        default=0.0,
        help='Số lượng trong hệ thống tại thời điểm quét'
    )
    
    # Chênh lệch = scanned - theoretical
    difference = fields.Float(
        string='Chênh lệch',
        compute='_compute_difference',
        store=True,
        help='Số lượng thực tế - Số lượng lý thuyết'
    )
    
    # Thông tin bổ sung
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial Number')
    package_id = fields.Many2one('stock.quant.package', string='Package')
    
    # Related fields for convenience
    user_id = fields.Many2one(
        'res.users',
        string='Scanned By',
        related='session_id.user_id',
        store=True
    )
    device_id = fields.Char(
        string='Device',
        related='session_id.device_id',
        store=True
    )
    
    # Timestamps
    create_date = fields.Datetime(string='Created', readonly=True)
    write_date = fields.Datetime(string='Last Updated', readonly=True)

    @api.depends('scanned_qty', 'theoretical_qty')
    def _compute_difference(self):
        for line in self:
            line.difference = line.scanned_qty - line.theoretical_qty

    def get_line_data(self):
        """Trả về dữ liệu line cho frontend"""
        self.ensure_one()
        return {
            'id': self.id,
            'product_id': self.product_id.id,
            'product_code': self.product_id.default_code or '',
            'product_name': self.product_id.display_name,
            'product_barcode': self.product_id.barcode or '',
            'uom_name': self.product_id.uom_id.name or 'Cái',
            'scanned_qty': self.scanned_qty,
            'theoretical_qty': self.theoretical_qty,
            'difference': self.difference,
            'location_id': self.location_id.id if self.location_id else False,
            'location_name': self.location_id.display_name if self.location_id else '',
            'lot_id': self.lot_id.id if self.lot_id else False,
            'lot_name': self.lot_id.name if self.lot_id else '',
            'package_id': self.package_id.id if self.package_id else False,
            'package_name': self.package_id.name if self.package_id else '',
        }
