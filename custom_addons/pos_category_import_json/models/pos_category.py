from odoo import models, fields

class PosCategory(models.Model):
    _inherit = 'pos.category'

    x_misa_id = fields.Integer(string='MISA ID', help="ID from MISA system for synchronization")
