# -*- coding: utf-8 -*-
{
    'name': 'Milwaukee Pricing Sync (HLV)',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Synchronize product prices from Odoo to Milwaukee Website',
    'description': """
        Module to synchronize prices from Odoo to Milwaukee website via REST API.
        - regularPrice mapping: x_studio_ga_web
        - salePrice mapping: milwaukee_sale_price
        - Product matching: SKU (default_code)
    """,
    'author': 'Antigravity (DeepMind)',
    'website': 'https://hoanglongvu.com',
    'depends': ['product', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/milwaukee_config_views.xml',
        'views/milwaukee_pricing_views.xml',
        'views/product_template_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
