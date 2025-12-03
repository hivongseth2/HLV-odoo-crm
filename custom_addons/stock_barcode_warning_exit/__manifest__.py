{
    'name': 'Stock Barcode Exit Warning',
    'version': '1.0',
    'category': 'Inventory/Inventory',
    'summary': 'Cảnh báo khi thoát App Barcode nếu phiếu đang giữ hàng',
    'description': """
        Module này hiển thị cảnh báo popup khi người dùng nhấn nút Thoát (Back) 
        trong ứng dụng Barcode nếu phiếu kho đang ở trạng thái giữ hàng (Reserved).
        Giúp ngăn chặn tình trạng treo tồn kho do thoát đột ngột.
    """,
    'depends': ['stock_barcode', 'web'],
    'assets': {
        'web.assets_backend': [
            'stock_barcode_warning_exit/static/src/js/main_component_patch.js',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}


