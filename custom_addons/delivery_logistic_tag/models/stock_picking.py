from odoo import models, fields

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    delivery_note_attachment = fields.Binary("Delivery Note", attachment=True)
    delivery_note_filename = fields.Char("Filename")