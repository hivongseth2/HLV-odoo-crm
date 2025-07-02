from odoo import models, fields

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    delivery_note_attachment = fields.Binary("Delivery Note", attachment=True)
    delivery_note_filename = fields.Char("Filename")
    
    def print_logistic_tag(self):
        return self.env.ref('delivery_logistic_tag.report_logistic_tag').report_action(self)