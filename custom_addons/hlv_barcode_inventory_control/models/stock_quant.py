from odoo import models, _
from odoo.exceptions import UserError


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def action_apply_inventory(self):
        """Chỉ cho phép user có quyền Inventory Validator mới được apply."""
        if not self.env.user.has_group(
            'hlv_barcode_inventory_control.group_inventory_validator'
        ):
            raise UserError(_(
                'Bạn không có quyền xác nhận kiểm kê tồn kho.\n'
                'Vui lòng liên hệ quản lý kho để duyệt.'
            ))
        return super().action_apply_inventory()
