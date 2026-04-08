# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ShopeeEscrowDetailWizard(models.TransientModel):
    _name = 'shopee.escrow.detail.wizard'
    _description = 'Chi tiết Escrow Shopee'

    order_id = fields.Many2one('sale.order', string='Đơn hàng', readonly=True)
    escrow_html = fields.Html(string='Chi tiết Escrow', readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and self.env.context.get('active_model') == 'sale.order':
            order = self.env['sale.order'].browse(active_id)
            res['order_id'] = order.id
            res['escrow_html'] = self._build_escrow_html(order.shopee_escrow_data)
        return res

    def _build_escrow_html(self, escrow_data):
        return shopee_escrow.build_escrow_html_common(escrow_data, is_wizard=True)
