
from odoo import fields, models, api
import logging

_logger = logging.getLogger(__name__)

def run_debug(env):
    skus_to_check = [
        '06011B40K0',
        '06011A03K1',
        '06112A60K1',
        '0611251604',
        '0611253604'
    ]
    
    print("\n" + "="*50)
    print("SEARCH DEBUG REPORT")
    print("="*50)
    
    ProductTemplate = env['product.template'].sudo()
    ProductProduct = env['product.product'].sudo()
    
    for sku in skus_to_check:
        print(f"\nChecking SKU: [{sku}]")
        
        # 1. Exact Search on Template
        tmpl = ProductTemplate.search([('default_code', '=', sku)])
        print(f"  - Template Search (=): Found {len(tmpl)} records")
        for t in tmpl:
            print(f"    > ID: {t.id}, Name: {t.name}, Code: {repr(t.default_code)}, Active: {t.active}")

        # 2. Case Insensitive Search on Template
        tmpl_ilike = ProductTemplate.search([('default_code', '=ilike', sku)])
        print(f"  - Template Search (=ilike): Found {len(tmpl_ilike)} records")
        for t in tmpl_ilike:
            print(f"    > ID: {t.id}, Name: {t.name}, Code: {repr(t.default_code)} vs Input '{sku}'")

        # 3. Search on Product Variant
        prod = ProductProduct.search([('default_code', '=', sku)])
        print(f"  - Product Variant Search (=): Found {len(prod)} records")
        for p in prod:
            print(f"    > ID: {p.id}, TmplID: {p.product_tmpl_id.id}, Code: {repr(p.default_code)}")

        # 4. Search Including Archived
        tmpl_archived = ProductTemplate.with_context(active_test=False).search([('default_code', '=', sku)])
        if len(tmpl_archived) > len(tmpl):
            print(f"  - Archived Search: Found {len(tmpl_archived)} (Some are archived)")
            for t in tmpl_archived:
                if not t.active:
                    print(f"    > ARCHIVED: ID: {t.id}, Code: {repr(t.default_code)}")

run_debug(self.env)
