# -*- coding: utf-8 -*-
from odoo import api, models

class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.depends('name', 'parent_id.name', 'type', 'company_name')
    @api.depends_context('show_shipping_name_only')
    def _compute_display_name(self):
        if self._context.get('show_shipping_name_only'):
            for partner in self:
                # Chỉ hiển thị tên người nhận, không kèm tên công ty cha
                partner.display_name = partner.name or ''
        else:
            super()._compute_display_name()
