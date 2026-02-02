# -*- coding: utf-8 -*-
from odoo import models, fields


class HlvChatgptTag(models.Model):
    _name = 'hlv.chatgpt.tag'
    _description = 'HLV Chat Tag'
    _order = 'name'

    name = fields.Char(required=True, index=True)
    color = fields.Integer(default=0)
