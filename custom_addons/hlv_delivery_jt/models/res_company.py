# -*- coding: utf-8 -*-
from odoo import fields, models

class ResCompany(models.Model):
    _inherit = "res.company"

    jt_environment = fields.Selection([
        ('test', 'Test / UAT'),
        ('prod', 'Production')
    ], string="J&T Environment", default='test')
