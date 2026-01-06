# -*- coding: utf-8 -*-
from odoo import models, fields

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_pos_payment_method = fields.Char(string="Hình thức thanh toán POS")
