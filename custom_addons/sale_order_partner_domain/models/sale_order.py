# -*- coding: utf-8 -*-
from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.depends('partner_id')
    def _compute_partner_shipping_id(self):
        for order in self:
            order.partner_shipping_id = order.partner_shipping_id or order.partner_id.address_get(['delivery'])['delivery']

    partner_shipping_id = fields.Many2one(
        'res.partner',
        string='Delivery Address',
        compute='_compute_partner_shipping_id',
        store=True,
        readonly=False,
        precompute=True,
    )

