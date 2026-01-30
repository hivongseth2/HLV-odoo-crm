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
        import logging
        _logger = logging.getLogger(__name__)
        
        if not args:
            args = []
            
        # 1. Get initial search results from super()
        # We need to fetch many more results because single products might be ranked lower
        # by Odoo's default search, and we want to bring them to the top
        search_limit = limit * 10 if limit else None
        res = super(ProductProduct, self).name_search(name=name, args=args, operator=operator, limit=search_limit)
        
        if not res:
            return []

        # Log original results
        _logger.info(f"HLV Search ORIGINAL (first 5): {[x[1] for x in res[:5]]}")

        # Extract IDs from the search results (res is a list of tuples (id, display_name))
        product_ids = [x[0] for x in res]
        
        # 2. Find which of these products have BOMs
        # Products that have specific BOM variants
        boms_variant = self.env['mrp.bom'].search([('product_id', 'in', product_ids)]).mapped('product_id.id')
        
        # Products whose templates have BOMs (and no specific variant BOM overrides, or applies to all)
        products = self.browse(product_ids)
        product_tmpls_with_boms = self.env['mrp.bom'].search([
            ('product_tmpl_id', 'in', products.mapped('product_tmpl_id').ids),
            ('product_id', '=', False) 
        ]).mapped('product_tmpl_id.id')
        
        # 3. Partition results
        single_products = []
        combo_products_with_bom = []
        
        # Create a set of IDs that are "Combo" (have a BOM)
        combo_ids = set(boms_variant)
        for p in products:
            if p.product_tmpl_id.id in product_tmpls_with_boms:
                combo_ids.add(p.id)
        
        _logger.info(f"HLV Search: Found {len(product_ids)} products. Combo IDs count: {len(combo_ids)}, Single count: {len(product_ids) - len(combo_ids)}")

        for r in res:
            p_id = r[0]
            if p_id in combo_ids:
                combo_products_with_bom.append(r)
            else:
                single_products.append(r)
                
        # 4. Construct final sorted list
        # We prioritize single products, then combo products.
        sorted_res = single_products + combo_products_with_bom
        
        # Log sorted results
        _logger.info(f"HLV Search SORTED (first 5): {[x[1] for x in sorted_res[:5]]}")
        
        # 5. Apply the original limit
        if limit:
            return sorted_res[:limit]
        return sorted_res
