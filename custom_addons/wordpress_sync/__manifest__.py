{
    'name': 'WordPress Price Synchronization',
    'version': '18.0.1.0.0',
    'summary': 'Đồng bộ giá sản phẩm từ Odoo lên WordPress/WooCommerce',
    'description': '''
        Module đồng bộ giá sản phẩm từ Odoo lên WordPress/WooCommerce:
        - Tự động đồng bộ khi giá thay đổi (x_studio_ga_web, x_studio_gi_bn_thng_mi)
        - Đồng bộ thủ công từng sản phẩm hoặc tất cả
        - Lưu log chi tiết từng lần đồng bộ
        - Cài đặt trong Inventory Settings
    ''',
    'author': 'HLV',
    'category': 'Website',
    'license': 'LGPL-3',
    'depends': ['base', 'product', 'stock', 'website', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/wordpress_config_view.xml',
        'views/wordpress_price_sync_view.xml',
        'views/product_sync_log_view.xml',
        'views/product_template_view.xml',
        'views/res_config_settings_views.xml',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
