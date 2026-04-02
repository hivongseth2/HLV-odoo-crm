from odoo import models, api, _
from odoo.exceptions import UserError


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def _check_inventory_permission(self):
        """Kiểm tra quyền cập nhật tồn kho."""
        if self.env.su:
            return
        Permission = self.env['warehouse.user.permission']
        for quant in self:
            warehouse = quant.location_id.warehouse_id
            if warehouse and not Permission.check_permission(
                    self.env.user, warehouse, 'can_update_inventory'):
                raise UserError(_(
                    'Bạn không có quyền cập nhật tồn kho tại kho "%(warehouse)s".\n'
                    'Vui lòng liên hệ quản trị viên.',
                    warehouse=warehouse.name,
                ))

    def action_apply_inventory(self):
        """Kiểm tra quyền trước khi áp dụng kiểm kê."""
        self._check_inventory_permission()
        return super().action_apply_inventory()

    def write(self, vals):
        """Bỏ qua inventory fields nếu không có quyền (tránh popup lỗi lặp)."""
        inventory_fields = {'inventory_quantity', 'inventory_quantity_auto_apply', 'inventory_quantity_set'}
        matched = inventory_fields & set(vals)
        if matched and not self.env.su:
            Permission = self.env['warehouse.user.permission']
            blocked = False
            for quant in self:
                warehouse = quant.location_id.warehouse_id
                if warehouse and not Permission.check_permission(
                        self.env.user, warehouse, 'can_update_inventory'):
                    blocked = True
                    break
            if blocked:
                # Loại bỏ inventory fields, không raise lỗi để tránh popup lặp
                vals = {k: v for k, v in vals.items() if k not in inventory_fields}
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
