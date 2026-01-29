# -*- coding: utf-8 -*-
{
    'name': "HLV Product Crawler",
    'summary': """
        Crawl product specifications from ketnoitieudung.vn, visior.vn, thbvietnam.com""",
    'description': """
        This module allows users to fetch product technical specifications and details 
        from external websites directly from the Product form.
    """,
    'author': "Antigravity",
    'website': "https://www.example.com",
    'category': 'Inventory',
    'version': '18.0.0.1',
    'depends': ['product', 'web'],
    'external_dependencies': {
        'python': ['requests', 'bs4'],
    },
    'data': [
        'views/product_views.xml',
    ],
    'license': 'LGPL-3',
}
