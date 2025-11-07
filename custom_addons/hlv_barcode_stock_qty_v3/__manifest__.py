{
    'name': 'HLV Barcode Stock Quantity (v3 inline)',
    'version': '1.2.3',  # tăng version để Odoo rebuild assets
    'summary': 'Hiển thị tồn kho khi quét barcode (inline ngay sau 0/x Cái)',
    'author': 'HLV - Thanh Luan',
    'category': 'Inventory/Barcode',
    'depends': ['stock', 'stock_barcode'],

    'assets': {
        # 1) Những bundle có thể được dùng bởi Barcode app tùy biến thể/version
        'stock_barcode.assets_backend': [
            '/hlv_barcode_stock_qty_v3/static/src/js/barcode_inline_qty.js',
            '/hlv_barcode_stock_qty_v3/static/src/css/inline.css',
        ],
        'stock_barcode.assets_common': [
            '/hlv_barcode_stock_qty_v3/static/src/js/barcode_inline_qty.js',
            '/hlv_barcode_stock_qty_v3/static/src/css/inline.css',
        ],

        # 2) Luôn luôn nạp ở backend chung (phương án cứu cánh)
        'web.assets_backend': [
            '/hlv_barcode_stock_qty_v3/static/src/js/barcode_inline_qty.js',
            '/hlv_barcode_stock_qty_v3/static/src/css/inline.css',
        ],
    },

    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
