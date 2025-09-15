from odoo import models

class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_open_order_in_panel(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "hlv_show_panel_noqweb",
            "params": {"res_id": self.id},
        }