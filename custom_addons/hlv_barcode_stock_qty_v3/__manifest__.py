{
    'name': 'HLV Barcode Stock Quantity (inline)',
    'version': '1.3.1',
    'depends': ['stock', 'stock_barcode'],
    'data': [],
    'assets': {
        # ép vào cả frontend lẫn backend để chắc chắn
        'web.assets_frontend': [
            '/hlv_barcode_stock_qty_v3/static/src/js/barcode_inline_qty.js',
            '/hlv_barcode_stock_qty_v3/static/src/css/inline.css',
        ],
        'web.assets_backend': [
            '/hlv_barcode_stock_qty_v3/static/src/js/barcode_inline_qty.js',
            '/hlv_barcode_stock_qty_v3/static/src/css/inline.css',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
