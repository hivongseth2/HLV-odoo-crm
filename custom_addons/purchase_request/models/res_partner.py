# Copyright 2024-2026 Antigravity
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from odoo import api, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def _name_search(self, name, domain=None, operator="ilike", limit=100, order=None):
        if self._context.get("hlv_prioritize_company"):
            # Set order to prioritize companies
            order = f"is_company DESC, {order or 'name ASC'}"
        return super()._name_search(name, domain=domain, operator=operator, limit=limit, order=order)

    @api.model
    def search_fetch(self, domain, field_names, offset=0, limit=None, order=None):
        if self._context.get("hlv_prioritize_company"):
            # Ensure order prioritizes companies even in search_fetch (common in Odoo 18 UI)
            order = f"is_company DESC, {order or 'name ASC'}"
        return super().search_fetch(domain, field_names, offset, limit, order)
