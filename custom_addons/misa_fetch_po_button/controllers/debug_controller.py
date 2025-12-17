
# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class MisaDebugController(http.Controller):
    @http.route('/debug/check_sku', type='http', auth='public', csrf=False)
    def debug_check_sku(self, **kwargs):
        skus_to_check = [
            '06011B40K0',
            '06011A03K1',
            '06112A60K1',
            '0611251604',
            '0611253604'
        ]
        
        output = ["SEARCH DEBUG REPORT"]
        output.append("="*50)
        
        ProductTemplate = request.env['product.template'].sudo()
        ProductProduct = request.env['product.product'].sudo()
        
        for sku in skus_to_check:
            output.append(f"<br/>Checking SKU: <b>[{sku}]</b>")
            
            # 1. Exact Search on Template
            tmpl = ProductTemplate.search([('default_code', '=', sku)])
            output.append(f"- Template Search (=): Found {len(tmpl)} records")
            for t in tmpl:
                output.append(f"&nbsp;&nbsp;> ID: {t.id}, Name: {t.name}, Code: {repr(t.default_code)}, Active: {t.active}")

            # 2. Case Insensitive Search on Template
            tmpl_ilike = ProductTemplate.search([('default_code', '=ilike', sku)])
            output.append(f"- Template Search (=ilike): Found {len(tmpl_ilike)} records")
            for t in tmpl_ilike:
                output.append(f"&nbsp;&nbsp;> ID: {t.id}, Name: {t.name}, Code: {repr(t.default_code)} vs Input '{sku}'")

            # 3. Search on Product Variant
            prod = ProductProduct.search([('default_code', '=', sku)])
            output.append(f"- Product Variant Search (=): Found {len(prod)} records")
            for p in prod:
                output.append(f"&nbsp;&nbsp;> ID: {p.id}, TmplID: {p.product_tmpl_id.id}, Code: {repr(p.default_code)}")

            # 4. Search Including Archived
            tmpl_archived = ProductTemplate.with_context(active_test=False).search([('default_code', '=', sku)])
            if len(tmpl_archived) > len(tmpl):
                output.append(f"- Archived Search: Found {len(tmpl_archived)} (Some are archived)")
                for t in tmpl_archived:
                    if not t.active:
                        output.append(f"&nbsp;&nbsp;> ARCHIVED: ID: {t.id}, Code: {repr(t.default_code)}")

        return "<br/>".join(output)
