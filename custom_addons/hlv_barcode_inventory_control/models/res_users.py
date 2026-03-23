from odoo import models, fields


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _is_inventory_validator(self):
        """Helper để check quyền từ JS qua RPC nếu cần."""
        self.ensure_one()
        return self.has_group(
            'hlv_barcode_inventory_control.group_inventory_validator'
        )
