# -*- coding: utf-8 -*-
from odoo import models, fields

class HlvContactFilterTag(models.Model):
    _name = 'hlv.contact.filter.tag'
    _description = 'Contact Filter Tag'
    _order = 'sequence, id'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(default=10)
