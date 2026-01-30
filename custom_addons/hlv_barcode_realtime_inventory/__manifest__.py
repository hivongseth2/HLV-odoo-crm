{
    'name': 'HLV Inventory Scanner',
    'version': '18.0.1.0.0',
    'summary': 'Standalone barcode inventory scanner với real-time sync',
    'description': """
        Module kiểm kê tồn kho độc lập sử dụng barcode:
        - Quét mã vị trí kho → Quét sản phẩm → Xác nhận
        - Real-time sync: mỗi lần quét được lưu ngay vào database
        - Khôi phục dữ liệu khi reload trang (không mất session)
        - Hiển thị chênh lệch giữa số lượng thực tế và lý thuyết
    """,
    'category': 'Inventory/Inventory',
    'author': 'HLV',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/inventory_scanner_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_barcode_realtime_inventory/static/src/components/inventory_scanner/inventory_scanner.js',
            'hlv_barcode_realtime_inventory/static/src/components/inventory_scanner/inventory_scanner.xml',
            'hlv_barcode_realtime_inventory/static/src/components/inventory_scanner/inventory_scanner.scss',
        ],
    },
    'installable': True,
    'application': True,  # Hiện trên trang chủ
    'auto_install': False,
    'sequence': 10,  # Thứ tự hiển thị
}
