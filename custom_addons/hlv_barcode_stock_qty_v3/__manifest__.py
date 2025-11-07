{
    'name': 'HLV Barcode Stock Quantity (v3 inline)',
    'version': '1.2.3',  # tăng version để Odoo rebuild assets
    'summary': 'Hiển thị tồn kho khi quét barcode (inline ngay sau 0/x Cái)',
    'author': 'HLV - Thanh Luan',
    'category': 'Inventory/Barcode',
    'depends': ['stock', 'stock_barcode'],
    'data': [
        'views/assets.xml',   # <-- QUAN TRỌNG
    ],
    'assets': {
        # có thể giữ, nhưng trọng tâm là assets.xml:
        'stock_barcode.assets_backend': [
            '/hlv_barcode_stock_qty_v3/static/src/js/barcode_inline_qty.js',
            '/hlv_barcode_stock_qty_v3/static/src/css/inline.css',
        ],
        'web.assets_backend': [
            '/hlv_barcode_stock_qty_v3/static/src/js/barcode_inline_qty.js',
            '/hlv_barcode_stock_qty_v3/static/src/css/inline.css',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
