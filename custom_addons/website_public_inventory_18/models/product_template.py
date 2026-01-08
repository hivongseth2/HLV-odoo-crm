# -*- coding: utf-8 -*-
from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    x_studio_ga_web = fields.Float(string="Giá Web")
    x_studio_gia_san_tmdt = fields.Float(string="Giá sàn TMDT")
    x_studio_ga_hng_nim_yt = fields.Float(string="Giá niêm yết")
    x_studio_gi_bn_thng_mi = fields.Float(string="Giá thương mại")
