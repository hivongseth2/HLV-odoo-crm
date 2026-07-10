# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ZaloMiniAppBanner(models.Model):
    _name = 'zalo.miniapp.banner'
    _description = 'Zalo Mini App Banner'
    _order = 'sequence, id'

    name = fields.Char(string='Banner Name', required=True)
    active = fields.Boolean(string='Active', default=True)
    sequence = fields.Integer(string='Sequence', default=10)
    image = fields.Image(string='Image', max_width=1024, max_height=1024, required=True)
    link = fields.Char(string='Link / URL', help="Deep link or external URL for the banner")
