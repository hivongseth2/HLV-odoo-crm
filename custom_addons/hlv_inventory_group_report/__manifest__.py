{
    'name': 'HLV Báo cáo tồn kho theo nhóm',
    'version': '1.1.1',
    'category': 'Inventory',
    'summary': 'Báo cáo tồn kho theo nhóm sản phẩm tuỳ chỉnh',
    'description': """
        Cho phép gom nhóm sản phẩm và báo cáo tồn kho theo từng nhóm.
        Một sản phẩm có thể thuộc nhiều nhóm báo cáo.
        Hiển thị số lượng tồn tại từng kho và tổng tất cả kho.
        Xuất báo cáo dạng PDF hoặc xem trực tiếp trên trình duyệt.
    """,
    'author': 'HLV',
    'depends': ['product', 'stock', 'purchase'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_report_group_views.xml',
        'views/product_search_views.xml',
        'views/inventory_report_config_views.xml',
        'views/inventory_report_wizard_views.xml',
        'views/inventory_report_result_views.xml',
        'report/inventory_report_template.xml',
        'views/stock_quick_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_inventory_group_report/static/src/css/stock_quick_view.css',
            'hlv_inventory_group_report/static/src/xml/stock_quick_view.xml',
            'hlv_inventory_group_report/static/src/js/stock_quick_product_manager.js',
            'hlv_inventory_group_report/static/src/js/stock_quick_view.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
