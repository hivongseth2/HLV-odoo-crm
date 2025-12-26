# -*- coding: utf-8 -*-
from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Create a Many2one field pointing to self to use standard Odoo link behavior
    sale_order_self_link = fields.Many2one(
        'sale.order', 
        string='Mã đơn hàng', 
        compute='_compute_self_link'
    )

    @api.depends('name')
    def _compute_self_link(self):
        for record in self:
            record.sale_order_self_link = record.id

    def action_view_order_detail(self):
        """
        Legacy method kept just in case.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.id,
            'view_mode': 'form',
            'view_type': 'form',
            'target': 'current',
        }
