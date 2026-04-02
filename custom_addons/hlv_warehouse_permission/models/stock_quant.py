from odoo import models, _
from odoo.exceptions import UserError


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def action_apply_inventory(self):
        """Kiểm tra quyền cập nhật tồn kho trước khi áp dụng."""
        if not self.env.su:
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
        return super().action_apply_inventory()
