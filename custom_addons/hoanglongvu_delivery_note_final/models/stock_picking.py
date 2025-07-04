from odoo import models

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def print_delivery_note(self):
        return self.env.ref('hoanglongvu_delivery_note.action_report_delivery_note').report_action(self)

    def print_logistic_tag(self):
        return self.env.ref('hoanglongvu_delivery_note.action_report_logistic_tag').report_action(self)
