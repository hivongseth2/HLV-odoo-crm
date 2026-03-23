{
    'name': 'HLV - Phân Quyền Kiểm Tồn Kho Barcode',
    'version': '18.0.1.0.0',
    'summary': 'Ẩn nút tồn kho trong barcode và phân quyền kiểm kê',
    'description': """
        Module này thực hiện:
        - Ẩn nút "Số lượng tồn kho" (o_button_inventory) trong giao diện Barcode
        - Phân quyền: Nhân viên có thể TẠO move line từ inventory adjustment
          nhưng KHÔNG THỂ xác nhận hoàn thành (apply inventory)
        - Chỉ người có quyền "Inventory Validator" mới được duyệt/hoàn thành
    """,
    'category': 'Inventory/Barcode',
    'author': 'HLV',
    'depends': ['stock', 'stock_barcode'],
    'data': [
        'security/hlv_inventory_control_security.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_barcode_inventory_control/static/src/js/hide_inventory_button.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
