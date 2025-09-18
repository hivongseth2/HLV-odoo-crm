# models/sale_order_misa_id.py
from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    misa_id = fields.Char(string="MISA ID", copy=False, index=True)