{
    'name': 'HLV Barcode Stock Quantity (inline)',
    'version': '1.3.2',
    'depends': ['stock', 'stock_barcode'],
    'data': [],
    'assets': {
        # ----------------------------------------------------------
        # ⚠️ BẮT BUỘC PHẢI LÀ 'stock_barcode.assets' ⚠️
        # Nếu để 'web.assets_backend' thì vào màn hình quét sẽ không chạy!
        # ----------------------------------------------------------
        'stock_barcode.assets': [
            'hlv_barcode_stock_qty_v3/static/src/css/inline.css',
            'hlv_barcode_stock_qty_v3/static/src/js/barcode_inline_qty.js',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}