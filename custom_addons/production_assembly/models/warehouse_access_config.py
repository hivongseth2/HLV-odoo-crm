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
        """Lấy danh sách vị trí mà user được phép truy cập (bao gồm vị trí con của kho)."""
        if not user_id:
            user_id = self.env.user.id

        user = self.env['res.users'].browse(user_id)

        # Nếu là superuser (odoo admin) thì cho full
        if user._is_superuser():
            return self.env['stock.location'].search([
                ('usage', 'in', ['internal', 'transit'])
            ])

        # Tìm config theo user
        config = self.search([
            ('user_id', '=', user.id),
            ('active', '=', True)
        ], limit=1)

        if not config:
            # Không có config => không thấy vị trí nào (hoặc bạn có thể cho full tùy policy)
            return self.env['stock.location']

        # Nếu là admin kho trong config thì cho full
        if config.is_admin:
            return self.env['stock.location'].search([
                ('usage', 'in', ['internal', 'transit'])
            ])

        # Lấy vị trí được gán trực tiếp
        accessible_locations = config.location_ids

        # Lấy tất cả vị trí con của các kho được phép truy cập
        for warehouse in config.warehouse_ids:
            warehouse_locations = self.env['stock.location'].search([
                ('id', 'child_of', warehouse.view_location_id.id),
                ('usage', 'in', ['internal', 'transit']),
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