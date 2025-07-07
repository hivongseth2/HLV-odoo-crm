
from odoo import models

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def print_logistic_tag(self):
        self.ensure_one()
        move_lines = self.move_line_ids.filtered(lambda l: l.qty_done > 0)
        return self.env.ref('logistic_tag_report.action_report_logistic_tag').report_action(move_lines)
