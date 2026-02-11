# -*- coding: utf-8 -*-

from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    shopee_delivery_status = fields.Char(string='Shopee Delivery Status', help="Status received from Shopee Webhook")
    
