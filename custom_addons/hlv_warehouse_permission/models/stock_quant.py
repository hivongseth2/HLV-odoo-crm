from odoo import models, api, _
from odoo.exceptions import UserError


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def _get_blocked_warehouse(self):
        """Trả về warehouse bị chặn (nếu có), hoặc False."""
        if self.env.su:
            return False
        Permission = self.env['warehouse.user.permission']
        for quant in self:
            warehouse = quant.location_id.warehouse_id
            if warehouse and not Permission.check_permission(
                    self.env.user, warehouse, 'can_update_inventory'):
                return warehouse
        return False

    def _send_permission_warning(self, warehouse):
        """Gửi toast notification cảnh báo không có quyền."""
        self.env['bus.bus']._sendone(
            self.env.user.partner_id,
            'simple_notification',
            {
                'title': _('Thao tác không hợp lệ'),
                'message': _(
                    'Bạn không có quyền cập nhật tồn kho tại kho "%(warehouse)s".\n'
                    'Vui lòng liên hệ quản trị viên.',
                    warehouse=warehouse.name,
                ),
                'type': 'warning',
                'sticky': True,
            },
        )

    def action_apply_inventory(self):
        """Chặn áp dụng kiểm kê nếu không có quyền (toast, không raise)."""
        blocked = self._get_blocked_warehouse()
        if blocked:
            self._send_permission_warning(blocked)
            return True
        return super().action_apply_inventory()

    def write(self, vals):
        """Strip inventory fields nếu không có quyền + gửi toast cảnh báo."""
        inventory_fields = {'inventory_quantity', 'inventory_quantity_auto_apply', 'inventory_quantity_set'}
        matched = inventory_fields & set(vals)
        if matched and not self.env.su:
            blocked = self._get_blocked_warehouse()
            if blocked:
                vals = {k: v for k, v in vals.items() if k not in inventory_fields}
                self.invalidate_recordset(fnames=list(matched))
                self._send_permission_warning(blocked)
                if not vals:
                    return True
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        """Chặn tạo quant với inventory quantity nếu không có quyền."""
        if not self.env.su:
            inventory_fields = {'inventory_quantity', 'inventory_quantity_auto_apply', 'inventory_quantity_set'}
            Permission = self.env['warehouse.user.permission']
            Location = self.env['stock.location']
            for vals in vals_list:
                if inventory_fields & set(vals):
                    location_id = vals.get('location_id')
                    if location_id:
                        location = Location.browse(location_id)
                        warehouse = location.warehouse_id
                        if warehouse and not Permission.check_permission(
                                self.env.user, warehouse, 'can_update_inventory'):
                            raise UserError(_(
                                'Bạn không có quyền cập nhật tồn kho tại kho "%(warehouse)s".\n'
                                'Vui lòng liên hệ quản trị viên.',
                                warehouse=warehouse.name,
                            ))
        return super().create(vals_list)
