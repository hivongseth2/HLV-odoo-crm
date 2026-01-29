# -*- coding: utf-8 -*-
from odoo import models, api

class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        """
        Override name_search to prioritize products WITHOUT a BOM (Single products)
        over products WITH a BOM (Combo products).
        """
        if not args:
            args = []
            
        # 1. Get initial search results from super()
        # We fetch more than the limit to ensure we have enough candidates to sort and filter
        # If we just fetch 'limit', we might miss some high-priority "single" products that 
        # would have appeared after the 'limit' cut-off in the default sort order.
        # However, fetching ALL results might be too slow. 
        # A reasonable compromise is fetching a larger batch if limit is set.
        search_limit = limit * 2 if limit else None
        res = super(ProductProduct, self).name_search(name=name, args=args, operator=operator, limit=search_limit)
        
        if not res:
            return []

        # Extract IDs from the search results (res is a list of tuples (id, display_name))
        product_ids = [x[0] for x in res]
        
        # 2. Find which of these products have BOMs
        # We search for BOMs where the product_id or product_tmpl_id matches our candidates.
        # Note: BOMs can be defined on product template or specific product variant.
        
        # Products that have specific BOM variants
        boms_variant = self.env['mrp.bom'].search([('product_id', 'in', product_ids)]).mapped('product_id.id')
        
        # Products whose templates have BOMs (and no specific variant BOM overrides, or applies to all)
        # We need to map back to product.product IDs.
        products = self.browse(product_ids)
        product_tmpls_with_boms = self.env['mrp.bom'].search([
            ('product_tmpl_id', 'in', products.mapped('product_tmpl_id').ids),
            ('product_id', '=', False) # BOM applies to all variants or template level
        ]).mapped('product_tmpl_id.id')
        
        # 3. Partition results
        single_products = []
        combo_products_with_bom = []
        
        # Create a set of IDs that are "Combo" (have a BOM)
        combo_ids = set(boms_variant)
        for p in products:
            if p.product_tmpl_id.id in product_tmpls_with_boms:
                combo_ids.add(p.id)
                
        for r in res:
            p_id = r[0]
            if p_id in combo_ids:
                combo_products_with_bom.append(r)
            else:
                single_products.append(r)
                
        # 4. Construct final sorted list
        # We prioritize single products, then combo products.
        sorted_res = single_products + combo_products_with_bom
        
        # 5. Apply the original limit
        if limit:
            return sorted_res[:limit]
        return sorted_res
