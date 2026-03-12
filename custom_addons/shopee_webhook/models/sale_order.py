# -*- coding: utf-8 -*-

from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    shopee_order_status = fields.Char(string='Shopee Order Status', help="Status received from Shopee Webhook (e.g. PROCESSED, COMPLETED)")
    
