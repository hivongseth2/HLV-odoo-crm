{
    'name': 'HLV - Phân Quyền Kho',
    'version': '18.0.1.0.0',
    'summary': 'Phân quyền chi tiết theo kho cho từng người dùng',
    'description': """
        Phân quyền kho hàng theo người dùng:
        - Ai được cập nhật tồn kho
        - Ai được tạo phiếu chuyển kho
        - Ai được xác nhận phiếu
        - Ai được thao tác với phiếu theo từng kho
        - Ẩn nút "Số lượng tồn kho" trong app Barcode
    """,
    'category': 'Inventory',
    'author': 'HLV',
    'depends': ['stock', 'stock_barcode'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/warehouse_permission_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_warehouse_permission/static/src/js/hide_inventory_button.js',
            'hlv_warehouse_permission/static/src/css/hide_inventory.css',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
