# -*- coding: utf-8 -*-
from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Define Studio fields explicitly to ensure they exist for the view
    # Note: If these fields already exist in the database (via Studio), 
    # declaring them here with the same name allows us to use them in code/views
    # without "Field not found" errors.

    x_studio_ga_web = fields.Monetary(string="Giá Web")
    x_studio_gi_bn_thng_mi = fields.Monetary(string="Giá Thương Mại")
    x_studio_ga_hng_nim_yt = fields.Monetary(string="Giá Niêm Yết")
