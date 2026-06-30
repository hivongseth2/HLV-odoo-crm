# Copyright 2024-2026 Antigravity
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from odoo import api, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def _get_hlv_priority_partner_ids(self):
        hlv_product_ids = self._context.get("hlv_product_ids")
        if hlv_product_ids:
            if isinstance(hlv_product_ids, (list, tuple)):
                product_ids = hlv_product_ids
            elif isinstance(hlv_product_ids, str) and hlv_product_ids.isdigit():
                product_ids = [int(hlv_product_ids)]
            else:
                product_ids = []

            if product_ids:
                suppliers = self.env["product.supplierinfo"].search([
                    ("product_tmpl_id", "in", self.env["product.product"].browse(product_ids).mapped("product_tmpl_id").ids)
                ])
                return suppliers.mapped("partner_id").ids
        return []

    @api.model
    def _name_search(self, name, domain=None, operator="ilike", limit=100, order=None):
        if not self._context.get("hlv_prioritize_company"):
            return super()._name_search(name, domain=domain, operator=operator, limit=limit, order=order)

        fallback_order = "is_company DESC, name ASC"
        priority_ids = self._get_hlv_priority_partner_ids()
        
        if not priority_ids:
            return super()._name_search(name, domain=domain, operator=operator, limit=limit, order=fallback_order)

        # 1. Search Priority Partners
        priority_domain = ['&', ('id', 'in', priority_ids)] + (domain or [])
        priority_res = super()._name_search(name, domain=priority_domain, operator=operator, limit=limit, order=fallback_order)

        if limit and len(priority_res) >= limit:
            return priority_res

        # 2. Search the rest
        rest_limit = limit - len(priority_res) if limit else None
        rest_domain = ['&', ('id', 'not in', priority_ids)] + (domain or [])
        rest_res = super()._name_search(name, domain=rest_domain, operator=operator, limit=rest_limit, order=fallback_order)

        return priority_res + rest_res

    @api.model
    def search_fetch(self, domain, field_names, offset=0, limit=None, order=None):
        if not self._context.get("hlv_prioritize_company"):
            return super().search_fetch(domain, field_names, offset, limit, order)

        fallback_order = "is_company DESC, name ASC"
        priority_ids = self._get_hlv_priority_partner_ids()

        if not priority_ids:
            return super().search_fetch(domain, field_names, offset, limit, fallback_order)

        priority_domain = ['&', ('id', 'in', priority_ids)] + (domain or [])
        priority_count = self.search_count(priority_domain)

        if offset < priority_count:
            # We fetch some priority records
            priority_limit = min(limit, priority_count - offset) if limit else None
            priority_recs = super().search_fetch(priority_domain, field_names, offset, priority_limit, fallback_order)

            if limit and len(priority_recs) >= limit:
                return priority_recs

            # Fetch the rest
            rest_limit = limit - len(priority_recs) if limit else None
            rest_domain = ['&', ('id', 'not in', priority_ids)] + (domain or [])
            rest_recs = super().search_fetch(rest_domain, field_names, 0, rest_limit, fallback_order)

            # Preserve order by concatenation
            return priority_recs.concat(rest_recs) if hasattr(priority_recs, 'concat') else priority_recs | rest_recs
        else:
            # We skipped all priority records via offset
            rest_offset = offset - priority_count
            rest_domain = ['&', ('id', 'not in', priority_ids)] + (domain or [])
            return super().search_fetch(rest_domain, field_names, rest_offset, limit, fallback_order)
