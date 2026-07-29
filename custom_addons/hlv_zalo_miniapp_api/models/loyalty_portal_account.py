# -*- coding: utf-8 -*-
from odoo import models, fields


class HlvLoyaltyPortalAccount(models.Model):
    _inherit = 'hlv.loyalty.portal.account'

    partner_id = fields.Many2one(
        'res.partner',
        domain=[('active', '=', True)],
    )
