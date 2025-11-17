# -*- coding: utf-8 -*-

from odoo import models, fields, api


class WarehouseAccessConfig(models.Model):
    _name = 'warehouse.access.config'
    _description = 'Cấu hình phân quyền truy cập kho'
    _rec_name = 'user_id'

    user_id = fields.Many2one(
        'res.users',
        string='Người dùng',
        required=True,
        ondelete='cascade'
    )
    
    location_ids = fields.Many2many(
        'stock.location',
        'warehouse_access_location_rel',
        'config_id',
        'location_id',
        string='Vị trí được phép truy cập',
        domain=[('usage', 'in', ['internal', 'transit'])]
    )
    
    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        'warehouse_access_warehouse_rel',
        'config_id',
        'warehouse_id',
        string='Kho được phép truy cập'
    )
    
    is_admin = fields.Boolean(
        string='Quản trị viên kho',
        default=False,
        help='Nếu được chọn, người dùng có thể truy cập tất cả các kho'
    )
    
    active = fields.Boolean(
        string='Hoạt động',
        default=True
    )
    
    @api.model
    def get_accessible_locations(self, user_id=None):
        """Lấy danh sách vị trí mà user được phép truy cập"""
        if not user_id:
            user_id = self.env.user.id
            
        # Kiểm tra nếu user là admin hoặc có quyền quản trị viên kho
        if self.env.user.has_group('stock.group_stock_manager'):
            return self.env['stock.location'].search([('usage', 'in', ['internal', 'transit'])])
            
        config = self.search([('user_id', '=', user_id), ('active', '=', True)], limit=1)
        
        if not config:
            # Nếu không có config, không cho phép truy cập vị trí nào
            return self.env['stock.location']
            
        if config.is_admin:
            # Nếu là admin kho, cho phép truy cập tất cả
            return self.env['stock.location'].search([('usage', 'in', ['internal', 'transit'])])
            
        # Lấy vị trí từ config trực tiếp và từ warehouse
        accessible_locations = config.location_ids
        
        # Thêm vị trí từ warehouse được phép truy cập
        for warehouse in config.warehouse_ids:
            warehouse_locations = self.env['stock.location'].search([
                ('id', 'child_of', warehouse.view_location_id.id),
                ('usage', 'in', ['internal', 'transit'])
            ])
            accessible_locations |= warehouse_locations
            
        return accessible_locations
    
    @api.model
    def get_locations_with_stock(self, product_id, user_id=None):
        """Lấy danh sách vị trí có tồn kho của sản phẩm và user được phép truy cập"""
        accessible_locations = self.get_accessible_locations(user_id)
        
        if not accessible_locations:
            return self.env['stock.location']
            
        # Tìm vị trí có tồn kho > 0
        quants = self.env['stock.quant'].search([
            ('product_id', '=', product_id),
            ('quantity', '>', 0),
            ('location_id', 'in', accessible_locations.ids)
        ])
        
        return quants.mapped('location_id')