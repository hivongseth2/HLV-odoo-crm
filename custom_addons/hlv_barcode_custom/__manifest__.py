{
    'name': 'HLV - Custom Barcode Operations',
    'version': '18.0.1.0.0',
    'summary': 'Custom barcode module for warehouse operations: Receipt, Delivery, Internal Transfer',
    'description': """
        Module Barcode tùy chỉnh cho Odoo 18:
        
        ✓ Nhập kho (Receipts) - Quét mã vạch ghi nhận hàng nhập
        ✓ Xuất kho (Delivery Orders) - Kiểm soát chặt chẽ sản phẩm & số lượng
        ✓ Chuyển vị trí (Internal Transfers) - Hỗ trợ quét kiện hàng (Packages)
        ✓ Tra cứu sản phẩm (Global Search) - Popup tồn kho theo vị trí
        ✓ Server-side realtime validation - Đảm bảo dữ liệu chính xác
        ✓ Camera scanner & Hardware scanner support
        ✓ Phản hồi âm thanh & hình ảnh (Audio & Visual Feedback)
        ✓ BOM/Kit component display
        ✓ Decimal quantity support (+0.1 / Numpad)
        
        KHÔNG bao gồm tính năng kiểm kê tồn kho (Inventory Adjustment).
    """,
    'category': 'Inventory/Barcode',
    'author': 'HLV',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['stock', 'barcodes', 'mrp'],
    'data': [
        'security/ir.model.access.csv',
        'data/default_config.xml',
        'views/barcode_config_views.xml',
        'views/barcode_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_barcode_custom/static/src/components/action_registry.js',
            'hlv_barcode_custom/static/src/components/barcode_app/barcode_app.js',
            'hlv_barcode_custom/static/src/components/barcode_app/barcode_app.xml',
            'hlv_barcode_custom/static/src/components/barcode_app/barcode_app.scss',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'sequence': 10,
}
