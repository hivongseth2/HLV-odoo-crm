from odoo import models, fields, api, _

PICKING_TYPE_CODES = [
    ('IN', 'Phiếu nhập kho (IN)'),
    ('OUT', 'Phiếu xuất hàng (OUT)'),
    ('INT', 'Phiếu chuyển nội bộ (INT)'),
    ('PICK', 'Phiếu lấy hàng (PICK)'),
    ('PACK', 'Phiếu đóng gói (PACK)'),
    ('STO', 'Phiếu lưu kho (STO)'),
]


class HlvBarcodeUserPermission(models.Model):
    _name = 'hlv.barcode.user.permission'
    _description = 'Phân quyền quét kho theo người dùng'
    _order = 'user_id, warehouse_id'

    user_id = fields.Many2one(
        'res.users', string='Người dùng', required=True, ondelete='cascade',
        domain=[('share', '=', False)])
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho', required=True, ondelete='cascade')
    picking_permission_ids = fields.One2many(
        'hlv.barcode.picking.permission', 'permission_id',
        string='Phân quyền phiếu quét')

    _sql_constraints = [
        ('user_warehouse_uniq', 'unique(user_id, warehouse_id)',
         'Mỗi người dùng chỉ có một bản ghi phân quyền cho mỗi kho!')
    ]

    def _compute_display_name(self):
        for rec in self:
            user_name = rec.user_id.name or ''
            wh_name = rec.warehouse_id.name or ''
            rec.display_name = f'{user_name} - {wh_name}'

    def action_open_detail(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hlv.barcode.user.permission',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    @api.model
    def configure_default_odoo_barcode_access(self):
        """Attach the dedicated access group to Odoo's default Barcode action/menu."""
        group = self.env.ref(
            'hlv_mobile_barcode.group_stock_barcode_default_user',
            raise_if_not_found=False,
        )
        if not group:
            return True

        actions = self.env['ir.actions.client'].sudo()
        action = self.env.ref(
            'stock_barcode.stock_barcode_action_main_menu',
            raise_if_not_found=False,
        )
        if action:
            actions |= action
        actions |= self.env['ir.actions.client'].sudo().search([
            ('tag', 'in', ['stock_barcode_main_menu', 'stock_barcode.MainMenu']),
        ])

        if actions and 'groups_id' in actions._fields:
            actions.write({'groups_id': [(4, group.id)]})

        menus = self.env['ir.ui.menu'].sudo()
        for action in actions:
            menus |= self.env['ir.ui.menu'].sudo().search([
                ('action', '=', 'ir.actions.client,%s' % action.id),
            ])

        for xmlid in ['stock_barcode.stock_barcode_main_menu', 'stock_barcode.stock_barcode_menu']:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu:
                menus |= menu

        if menus:
            menus.write({'groups_id': [(4, group.id)]})

        return True

    @api.model
    def check_picking_operation(self, user, warehouse, picking_type_code, operation_field):
        """Check if user can perform scan operation on a specific picking type at warehouse inside the Barcode Mobile App.

        operation_field: 'can_view', 'can_edit', 'can_delete', 'can_confirm'
        """
        if user._is_superuser():
            return True
        has_any = self.sudo().search_count([('user_id', '=', user.id)], limit=1)
        if not has_any:
            # If user has no barcode permission record at all, allow all by default
            return True
        perm = self.sudo().search([
            ('user_id', '=', user.id),
            ('warehouse_id', '=', warehouse.id),
        ], limit=1)
        if not perm:
            # If user has permissions for other warehouses but not this one, restrict access
            return False
        line = perm.picking_permission_ids.filtered(
            lambda l: l.picking_type_code == picking_type_code
        )
        if not line:
            return False
        return bool(line[0][operation_field])

    @api.model
    def action_generate_all(self):
        """Tạo phân quyền barcode cho tất cả user nội bộ × tất cả kho (mặc định bật hết)."""
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
                        'picking_permission_ids': [
                            (0, 0, {
                                'picking_type_code': code,
                                'can_view': True,
                                'can_edit': True,
                                'can_delete': True,
                                'can_confirm': True,
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
                'message': _('Đã tạo %d bản ghi phân quyền quét mới.') % len(vals_list),
                'type': 'success',
                'sticky': False,
            }
        }


class HlvBarcodePickingPermission(models.Model):
    _name = 'hlv.barcode.picking.permission'
    _description = 'Phân quyền loại phiếu quét chi tiết'
    _order = 'picking_type_code'

    permission_id = fields.Many2one(
        'hlv.barcode.user.permission', string='Phân quyền quét kho',
        required=True, ondelete='cascade')
    picking_type_code = fields.Selection(
        PICKING_TYPE_CODES, string='Loại phiếu', required=True)
    can_view = fields.Boolean('Xem / Quét', default=True)
    can_edit = fields.Boolean('Sửa / Quét hàng', default=True)
    can_delete = fields.Boolean('Xóa dòng', default=True)
    can_confirm = fields.Boolean('Xác nhận phiếu', default=True)

    _sql_constraints = [
        ('permission_type_uniq', 'unique(permission_id, picking_type_code)',
         'Mỗi loại phiếu chỉ được cấu hình một lần cho mỗi phân quyền!')
    ]
