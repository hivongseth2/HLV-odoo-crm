{
    'name': 'WordPress Price Synchronization',
    'version': '1.0',
    'depends': ['base', 'product', 'website'],
    'author': 'HLV',
    'category': 'Website',
    'description': 'Sync product prices from Odoo to WordPress automatically when prices are updated',
    'data': [
        'security/ir.model.access.csv',
        'views/wordpress_config_view.xml',
        'views/wordpress_price_sync_view.xml',
        'views/product_sync_log_view.xml',
        'views/product_template_view.xml',
    ],
    'installable': True,
    'auto_install': False,
}
