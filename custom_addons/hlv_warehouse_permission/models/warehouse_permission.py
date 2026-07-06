from odoo import models, fields, api, _

PICKING_TYPE_CODES = [
    ('IN', 'Phiếu nhập kho'),
    ('OUT', 'Phiếu xuất kho'),
    ('INT', 'Phiếu chuyển nội bộ'),
    ('PICK', 'Phiếu lấy hàng'),
    ('PACK', 'Phiếu đóng gói'),
    ('STO', 'Phiếu lưu kho'),
]


class WarehouseUserPermission(models.Model):
    _name = 'warehouse.user.permission'
    _description = 'Phân quyền kho theo người dùng'
    _order = 'user_id, warehouse_id'

    user_id = fields.Many2one(
        'res.users', string='Người dùng', required=True, ondelete='cascade',
        domain=[('share', '=', False)])
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho', required=True, ondelete='cascade')
    can_update_inventory = fields.Boolean(
        'Cập nhật tồn kho', default=False,
        help='Cho phép cập nhật/áp dụng kiểm kê tồn kho tại kho này')
    picking_permission_ids = fields.One2many(
        'warehouse.picking.permission', 'permission_id',
        string='Phân quyền phiếu')

    _sql_constraints = [
        ('user_warehouse_uniq', 'unique(user_id, warehouse_id)',
         'Mỗi người dùng chỉ có một bản ghi phân quyền cho mỗi kho!')
    ]

    def _compute_display_name(self):
        for rec in self:
            user_name = rec.user_id.name or ''
            wh_name = rec.warehouse_id.name or ''
            rec.display_name = f'{user_name} - {wh_name}'

    @api.model
    def check_permission(self, user, warehouse, permission_field):
        """Check inventory permission (can_update_inventory)."""
        if user._is_superuser():
            return True
        has_any = self.sudo().search_count([('user_id', '=', user.id)], limit=1)
        if not has_any:
            return True
        perm = self.sudo().search([
            ('user_id', '=', user.id),
            ('warehouse_id', '=', warehouse.id),
        ], limit=1)
        return bool(perm and perm[permission_field])

    @api.model
    def check_picking_operation(self, user, warehouse, picking_type_code, operation_field):
        """Check if user can perform operation on a specific picking type at warehouse.

        operation_field: 'can_view', 'can_create', 'can_edit', 'can_delete', 'can_confirm', 'can_cancel'
        """
        if user._is_superuser():
            return True
        has_any = self.sudo().search_count([('user_id', '=', user.id)], limit=1)
        if not has_any:
            return True
        perm = self.sudo().search([
            ('user_id', '=', user.id),
            ('warehouse_id', '=', warehouse.id),
        ], limit=1)
        if not perm:
            return False
        line = perm.picking_permission_ids.filtered(
            lambda l: l.picking_type_code == picking_type_code
        )
        if not line:
            return False
        return bool(line[0][operation_field])

    @api.model
    def action_generate_all(self):
        """Tạo phân quyền cho tất cả user nội bộ × tất cả kho (mặc định bật hết)."""
        users = self.env['res.users'].search([
            ('share', '=', False),
            ('active', '=', True),
        ])
        warehouses = self.env['stock.warehouse'].search([])
        existing = self.search([])
        existing_pairs = {(r.user_id.id, r.warehouse_id.id) for r in existing}

        vals_list = []
        for user in users:
            for wh in warehouses:
                if (user.id, wh.id) not in existing_pairs:
                    vals_list.append({
                        'user_id': user.id,
                        'warehouse_id': wh.id,
                        'can_update_inventory': True,
                        'picking_permission_ids': [
                            (0, 0, {
                                'picking_type_code': code,
                                'can_view': True,
                                'can_create': True,
                                'can_edit': True,
                                'can_delete': True,
                                'can_confirm': True,
                                'can_cancel': True,
                            }) for code, _label in PICKING_TYPE_CODES
                        ],
                    })

        if vals_list:
            self.create(vals_list)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Hoàn thành'),
                'message': _('Đã tạo %d bản ghi phân quyền mới.') % len(vals_list),
                'type': 'success',
                'sticky': False,
            }
        }


class WarehousePickingPermission(models.Model):
    _name = 'warehouse.picking.permission'
    _description = 'Phân quyền loại phiếu chi tiết'
    _order = 'picking_type_code'

    permission_id = fields.Many2one(
        'warehouse.user.permission', string='Phân quyền kho',
        required=True, ondelete='cascade')
    picking_type_code = fields.Selection(
        PICKING_TYPE_CODES, string='Loại phiếu', required=True)
    can_view = fields.Boolean('Xem', default=True)
    can_create = fields.Boolean('Tạo', default=True)
    can_edit = fields.Boolean('Sửa', default=True)
    can_delete = fields.Boolean('Xóa', default=True)
    can_confirm = fields.Boolean('Xác nhận', default=True)
    can_cancel = fields.Boolean('Hủy', default=True)

    _sql_constraints = [
        ('permission_type_uniq', 'unique(permission_id, picking_type_code)',
         'Mỗi loại phiếu chỉ được cấu hình một lần cho mỗi phân quyền!')
    ]
