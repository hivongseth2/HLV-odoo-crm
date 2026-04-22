# -*- coding: utf-8 -*-
{
    'name': 'Milwaukee Pricing Sync (HLV)',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Synchronize product prices from Odoo to Milwaukee Website',
    'description': """
        Module to synchronize prices from Odoo to Milwaukee website via REST API.
        - regularPrice mapping: x_studio_ga_hng_nim_yt
        - salePrice mapping: x_studio_gi_web
        - Product matching: SKU (default_code)
    """,
    'author': 'Antigravity (DeepMind)',
    'website': 'https://hoanglongvu.com',
    'depends': ['product', 'mail', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/milwaukee_price_sync_wizard_views.xml',
        'views/milwaukee_pricing_views.xml',
        'views/product_template_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
