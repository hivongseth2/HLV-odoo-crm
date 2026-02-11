# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    alias_ids = fields.One2many('product.alias', 'product_id', string='Aliases')
