# -*- coding: utf-8 -*-
from odoo import api, models

class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def name_get(self):
        result = []
        for partner in self:
            if self._context.get('show_shipping_name_only'):
                if partner.type in ['contact', 'delivery'] and partner.parent_id:
                    name = partner.name
                else:
                    name = partner.name
            else:
                name = partner.display_name

            result.append((partner.id, name))
        return result
