from odoo import models

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_print_label(self):
        return self.env.ref('sale_order_label.report_sale_order_label').report_action(self)
