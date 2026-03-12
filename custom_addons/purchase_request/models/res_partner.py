# Copyright 2024-2026 Antigravity
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from odoo import api, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def _get_hlv_priority_order(self, order):
        hlv_product_ids = self._context.get("hlv_product_ids")
        if hlv_product_ids:
            # If hlv_product_ids is passed as a list of IDs or a RecordSet (unexpected but possible) 
            # or if it's a string like 'hlv_product_ids' (from XML context), we need to handle it.
            # However, in Odoo 18 UI, if we pass 'hlv_product_ids' in context, it will look it up in the view state.
            # But here in the backend, we expect the ACTUAL IDs.
            
            # If the context value is a list of IDs, we can use it.
            if isinstance(hlv_product_ids, (list, tuple)):
                product_ids = hlv_product_ids
            elif isinstance(hlv_product_ids, str) and hlv_product_ids.isdigit():
                product_ids = [int(hlv_product_ids)]
            else:
                product_ids = []

            if product_ids:
                # Find partners who are suppliers for these product
                suppliers = self.env["product.supplierinfo"].search([
                    ("product_tmpl_id", "in", self.env["product.product"].browse(product_ids).mapped("product_tmpl_id").ids)
                ])
                product_partner_ids = suppliers.mapped("partner_id").ids
                if product_partner_ids:
                    # Odoo SQL order: TRUE > FALSE. So "(id IN (...)) DESC" puts matches first.
                    partner_ids_str = ",".join(map(str, product_partner_ids))
                    order = f"(res_partner.id IN ({partner_ids_str})) DESC, is_company DESC, {order or 'name ASC'}"
                    return order

        # Default fallback to just company priority
        return f"is_company DESC, {order or 'name ASC'}"

    @api.model
    def _name_search(self, name, domain=None, operator="ilike", limit=100, order=None):
        if self._context.get("hlv_prioritize_company"):
            order = self._get_hlv_priority_order(order)
        return super()._name_search(name, domain=domain, operator=operator, limit=limit, order=order)

    @api.model
    def search_fetch(self, domain, field_names, offset=0, limit=None, order=None):
        if self._context.get("hlv_prioritize_company"):
            order = self._get_hlv_priority_order(order)
        return super().search_fetch(domain, field_names, offset, limit, order)
