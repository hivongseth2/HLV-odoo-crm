from odoo import models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_print_label(self):
        return self.env.ref('sale_order_label.action_report_stock_picking_label').report_action(self)
