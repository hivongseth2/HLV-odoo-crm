{
    'name': 'HLV Barcode Stock Quantity (inline)',
    'version': '1.3.3',
    'depends': ['stock', 'stock_barcode',"web"],
    'data': [],
    'assets': {
        # Load cả 2 nơi để 
        'web.assets_backend': [
            'hlv_barcode_stock_qty_v3/static/src/js/barcode_inline_qty.js',
            'hlv_barcode_stock_qty_v3/static/src/css/inline.css',
        ]
       
    },
    'installable': True,
    'license': 'LGPL-3',
}