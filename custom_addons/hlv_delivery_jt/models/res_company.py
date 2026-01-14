# -*- coding: utf-8 -*-
from odoo import fields, models

class ResCompany(models.Model):
    _inherit = "res.company"

    jt_customer_code = fields.Char(string="J&T Customer Code")
    jt_password = fields.Char(string="J&T Password")
    jt_environment = fields.Selection([
        ('test', 'Test / UAT'),
        ('prod', 'Production')
    ], string="J&T Environment", default='test')
