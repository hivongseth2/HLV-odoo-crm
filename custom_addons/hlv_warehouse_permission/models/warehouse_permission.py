from odoo import models, fields, api, _


class WarehouseUserPermission(models.Model):
    _name = 'warehouse.user.permission'
    _description = 'Phân quyền kho theo người dùng'
    _order = 'user_id, warehouse_id'

    user_id = fields.Many2one(
        'res.users', string='Người dùng', required=True, ondelete='cascade',
        domain=[('share', '=', False)])
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho', required=True, ondelete='cascade')
    can_receipt = fields.Boolean(
        'Phiếu nhập kho', default=False,
        help='Cho phép tạo/thao tác/xác nhận phiếu nhập kho (Receipts) tại kho này')
    can_delivery = fields.Boolean(
        'Phiếu xuất kho', default=False,
        help='Cho phép tạo/thao tác/xác nhận phiếu xuất kho (Delivery) tại kho này')
    can_internal = fields.Boolean(
        'Phiếu chuyển nội bộ', default=False,
        help='Cho phép tạo/thao tác/xác nhận phiếu chuyển hàng nội bộ (Internal) tại kho này')
    can_pick = fields.Boolean(
        'Phiếu lấy hàng', default=False,
        help='Cho phép tạo/thao tác/xác nhận phiếu lấy hàng (Pick) tại kho này')
    can_pack = fields.Boolean(
        'Phiếu đóng gói', default=False,
        help='Cho phép tạo/thao tác/xác nhận phiếu đóng gói (Pack) tại kho này')
    can_storage = fields.Boolean(
        'Phiếu lưu kho', default=False,
        help='Cho phép tạo/thao tác/xác nhận phiếu lưu kho (Storage) tại kho này')
    can_update_inventory = fields.Boolean(
        'Cập nhật tồn kho', default=False,
        help='Cho phép cập nhật/áp dụng kiểm kê tồn kho tại kho này')

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
        """Check if user has a specific permission for a warehouse.

        Returns True if:
        - User is superuser (OdooBot)
        - User has no permission records at all (chưa cấu hình → cho phép tất cả)
        - User has the specific permission for the warehouse

        Manager cũng bị hạn chế bởi phân quyền này.
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
        return bool(perm and perm[permission_field])

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
                        'can_receipt': True,
                        'can_delivery': True,
                        'can_internal': True,
                        'can_pick': True,
                        'can_pack': True,
                        'can_storage': True,
                        'can_update_inventory': True,
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
