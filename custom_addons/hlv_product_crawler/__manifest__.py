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
        'data/ir_cron_data.xml',
        'data/ir_actions_server.xml',
        'wizard/product_duplicate_wizard_views.xml',
        'views/product_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'license': 'LGPL-3',
}
