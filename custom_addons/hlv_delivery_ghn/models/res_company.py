# -*- coding: utf-8 -*-
from odoo import fields, models

class ResCompany(models.Model):
    _inherit = "res.company"

    ghn_api_token = fields.Char(string="GHN API Token")
    ghn_shop_id = fields.Integer(string="GHN Shop ID")
    ghn_environment = fields.Selection([
        ('test', 'Test / Sandbox'),
        ('prod', 'Production')
    ], string="GHN Environment", default='test')
