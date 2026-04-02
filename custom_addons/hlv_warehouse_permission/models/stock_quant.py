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
        """Chặn sửa inventory quantity nếu không có quyền."""
        inventory_fields = {'inventory_quantity', 'inventory_quantity_auto_apply', 'inventory_quantity_set'}
        if inventory_fields & set(vals) and not self.env.su:
            self._check_inventory_permission()
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        """Chặn tạo quant với inventory quantity nếu không có quyền."""
        inventory_fields = {'inventory_quantity', 'inventory_quantity_auto_apply', 'inventory_quantity_set'}
        records = super().create(vals_list)
        if any(inventory_fields & set(v) for v in vals_list) and not self.env.su:
            records._check_inventory_permission()
        return records
