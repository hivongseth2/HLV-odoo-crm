# -*- coding: utf-8 -*-
{
    'name': "HLV Product Search Override",
    'summary': "Override product name search to prioritize single products over combo products (BOM-based).",
    'description': """
        This module overrides the name_search method in product.product to ensure that:
        1. Products WITHOUT a BOM (Single products) appear at the top of search results.
        2. Products WITH a BOM (Combo/Manufactured products) appear after single products.
        This prioritization helps in selecting the correct components during sales or inventory operations where single items are preferred.
    """,
    'author': "Antigravity",
    'website': "https://www.example.com",
    'category': 'Product',
    'version': '0.1',
    'depends': ['product', 'mrp'],
    'data': [],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
