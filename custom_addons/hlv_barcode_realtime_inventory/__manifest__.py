{
    'name': 'HLV Inventory Check - Kiểm Kê Tồn Kho',
    'version': '18.0.1.0.3',
    'summary': 'Specialist inventory check module with barcode scanning and discrepancy tracking',
    'description': """
        Module kiểm kê tồn kho chuyên dụng cho Odoo 18:
        
        ✓ Quét vị trí → Quét sản phẩm → Đếm và xác nhận
        ✓ Lock toàn bộ inbound/outbound của vị trí đang kiểm kê
        ✓ Hiển thị số lượng lý thuyết và thực tế
        ✓ Cảnh báo nếu có outbound trong khi quét
        ✓ Cho phép người dùng nhập lý do chênh lệch
        ✓ Lưu chi tiết kiểm kê và so sánh
        ✓ Tạo Stock Adjustment tự động
        
        Features:
        - Real-time sync: Mỗi lần quét được lưu ngay vào database
        - Session recovery: Khôi phục dữ liệu khi reload trang
        - Move locking: Lock/Unlock stock moves của location
        - Discrepancy tracking: Theo dõi và ghi nhận lý do chênh lệch
        - Audit trail: Lưu toàn bộ thông tin kiểm kê
    """,
    'category': 'Inventory/Inventory',
    'author': 'HLV',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/inventory_check_views.xml',
        'views/inventory_check_line_views.xml',
        'views/inventory_discrepancy_views.xml',
        'views/inventory_scanner_views.xml',
        'data/sequence.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_barcode_realtime_inventory/static/src/components/action_registry.js',
            'hlv_barcode_realtime_inventory/static/src/components/inventory_check/inventory_check.js',
            'hlv_barcode_realtime_inventory/static/src/components/inventory_check/inventory_check.xml',
            'hlv_barcode_realtime_inventory/static/src/components/inventory_check/inventory_check.scss',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'sequence': 10,
}
