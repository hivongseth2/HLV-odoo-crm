# -*- coding: utf-8 -*-
from odoo import models, api
from odoo.osv import expression

from .common import tokenize_or_domain as _tokenize_or_domain, rewrite_free_text_domain as _rewrite_free_text_domain


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def search(self, domain, offset=0, limit=None, order=None, **kwargs):
        domain = _rewrite_free_text_domain(list(domain or []))
        return super(ProductProduct, self).search(domain, offset=offset, limit=limit, order=order, **kwargs)

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        """
        Override name_search to prioritize products WITHOUT a BOM (Single products)
        over products WITH a BOM (Combo products).

        Strategy: Do two separate searches at database level:
        1. Search products WITHOUT BOMs first
        2. Search products WITH BOMs second
        3. Combine results

        Also splits the query into tokens and matches each token against
        name/default_code/barcode with OR (a product must match ALL tokens,
        but each token can match ANY of the 3 fields). Same tokenizing logic
        as the /search_stock route (website_public_inventory_18/controllers/main.py).
        """
        import logging
        _logger = logging.getLogger(__name__)

        if not args:
            args = []

        original_query = name

        # --- Tokenized OR search: tách từng từ trong `name` rồi OR theo name/default_code/barcode ---
        if name:
            token_domain = _tokenize_or_domain(name)
            if token_domain:
                args = expression.AND([args, token_domain])
            # name đã được "tiêu thụ" thành domain ở trên, không cần super() match lại theo name nữa
            name = ''

        # Find all product IDs that have BOMs
        bom_model = self.env['mrp.bom']
        
        # Get product IDs with specific variant BOMs
        products_with_bom_variant = bom_model.search([
            ('product_id', '!=', False)
        ]).mapped('product_id.id')
        
        # Get product template IDs with template-level BOMs
        templates_with_bom = bom_model.search([
            ('product_id', '=', False)
        ]).mapped('product_tmpl_id.id')
        
        # Get all product IDs from those templates
        if templates_with_bom:
            products_from_templates = self.search([
                ('product_tmpl_id', 'in', templates_with_bom)
            ]).ids
        else:
            products_from_templates = []
        
        # Combine all product IDs that have BOMs
        all_combo_product_ids = list(set(products_with_bom_variant + products_from_templates))
        
        # Search 1: Products WITHOUT BOMs (Single products)
        single_args = args + [('id', 'not in', all_combo_product_ids)] if all_combo_product_ids else args
        single_results = super(ProductProduct, self).name_search(
            name=name, 
            args=single_args, 
            operator=operator, 
            limit=limit
        )
        
        # Search 2: Products WITH BOMs (Combo products)
        # Only search combos if we haven't filled the limit yet
        combo_results = []
        if all_combo_product_ids:
            remaining_limit = limit - len(single_results) if limit else None
            if remaining_limit is None or remaining_limit > 0:
                combo_args = args + [('id', 'in', all_combo_product_ids)]
                combo_results = super(ProductProduct, self).name_search(
                    name=name,
                    args=combo_args,
                    operator=operator,
                    limit=remaining_limit
                )
        
        # Combine results: Single products first, then combo products
        final_results = single_results + combo_results
        
        _logger.info(f"HLV Search: Query='{original_query}', Single={len(single_results)}, Combo={len(combo_results)}, Total={len(final_results)}")
        if final_results:
            _logger.info(f"HLV Search FINAL (first 3): {[x[1] for x in final_results[:3]]}")
        
        return final_results
