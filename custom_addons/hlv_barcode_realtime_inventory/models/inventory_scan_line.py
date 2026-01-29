# -*- coding: utf-8 -*-
from odoo import models, fields


class InventoryScanLine(models.Model):
    _name = 'inventory.scan.line'
    _description = 'Inventory Scan Line - Dòng quét từng lần'
    _order = 'scan_time desc'

    session_id = fields.Many2one('inventory.scan.session', string='Session', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', string='Product', required=True, index=True)
    location_id = fields.Many2one('stock.location', string='Location')
    
    quantity = fields.Float(string='Quantity', default=1.0, required=True, help='Số lượng mỗi lần quét (thường là 1)')
    scan_time = fields.Datetime(string='Scan Time', default=fields.Datetime.now, required=True, index=True)
    
    # Thông tin bổ sung (nếu cần)
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial Number')
    package_id = fields.Many2one('stock.quant.package', string='Package')
    
    user_id = fields.Many2one('res.users', string='Scanned By', related='session_id.user_id', store=True)
    device_id = fields.Char(string='Device', related='session_id.device_id', store=True)
