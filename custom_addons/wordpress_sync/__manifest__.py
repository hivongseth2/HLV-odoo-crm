{
    'name': 'WordPress Price & Stock Synchronization',
    'version': '18.0.2.0.0',
    'summary': 'Đồng bộ giá và tình trạng kho sản phẩm từ Odoo lên WordPress/WooCommerce',
    'description': '''
        Module đồng bộ giá và stock status sản phẩm từ Odoo lên WordPress/WooCommerce:
        - Tự động đồng bộ khi giá thay đổi (x_studio_ga_web, x_studio_gi_bn_thng_mi)
        - Đồng bộ thủ công từng sản phẩm hoặc tất cả
        - Đồng bộ tình trạng kho (stock status) lên WordPress
        - Tính giá bán combo tự động từ BOM (2 phương pháp)
        - Tự động cập nhật tình trạng combo khi sản phẩm con hết hàng
        - Lưu log chi tiết từng lần đồng bộ
        - Cài đặt trong Inventory Settings
    ''',
    'author': 'HLV',
    'category': 'Inventory',
    'license': 'LGPL-3',
    'depends': ['base', 'product', 'stock', 'mail', 'mrp'],
    'data': [
        'security/ir.model.access.csv',
        'views/wordpress_config_view.xml',
        'wizard/wordpress_update_stock_wizard_view.xml',
        'views/product_template_view.xml',
        'views/wordpress_price_sync_view.xml',
        'views/combo_stock_sync_view.xml',
        'views/wordpress_queue_view.xml',
        'views/res_config_settings_views.xml',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}

