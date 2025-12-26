# -*- coding: utf-8 -*-
from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    name_link = fields.Html(string='Số báo giá', compute='_compute_name_link')

    @api.depends('name')
    def _compute_name_link(self):
        for record in self:
            # Create a link to the form view of the order
            url = f'/web#id={record.id}&model=sale.order&view_type=form'
            # Use font-weight-bold to make it look like a primary field
            record.name_link = f'<a href="{url}" target="_blank" class="font-weight-bold" style="color: #017e84;">{record.name}</a>'

    def action_view_order_detail(self):
        """
        Legacy method kept just in case, or can be removed if strictly cleaning up.
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
