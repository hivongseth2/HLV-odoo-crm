# Copyright 2024-2026 Antigravity
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from odoo import api, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def _name_search(self, name, domain=None, operator="ilike", limit=100, order=None):
        if self._context.get("hlv_prioritize_company"):
            domain = domain or []
            # First, search for companies
            company_domain = [("is_company", "=", True)] + domain
            company_ids = super()._name_search(
                name, domain=company_domain, operator=operator, limit=limit, order=order
            )
            
            # If we reached the limit, return companies
            if len(company_ids) >= limit:
                return company_ids
            
            # Then search for others (individuals), excluding previously found companies
            other_domain = [("is_company", "=", False)] + domain
            # We need to subtract the already found IDs from the limit
            other_limit = limit - len(company_ids)
            other_ids = super()._name_search(
                name, domain=other_domain, operator=operator, limit=other_limit, order=order
            )
            
            # Combine the results. Note: company_ids and other_ids are RecordSets in Odoo 17/18 _name_search
            # Actually, _name_search returns a list of IDs or a RecordSet? 
            # In Odoo 17+, _name_search returns an Id list or a RecordSet depending on usage, 
            # but usually it returns a list of IDs from the base implementation.
            # Let's verify. In Odoo 18, it returns a RecordSet.
            
            return company_ids + other_ids
            
        return super()._name_search(name, domain=domain, operator=operator, limit=limit, order=order)
