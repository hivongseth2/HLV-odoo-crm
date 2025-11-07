# -*- coding: utf-8 -*-
{
    'name': 'HLV Barcode Stock Quantity (v3 inline)',
    'version': '1.2',
    'summary': 'Hiển thị tồn kho khi quét barcode (inline ngay sau 0/x Cái)',
    'author': 'HLV - Thanh Luan',
    'category': 'Inventory/Barcode',
    'depends': ['stock', 'stock_barcode'],
    'data': [],
    'assets': {
        'web.assets_backend': [
            '/hlv_barcode_stock_qty_v3/static/src/js/barcode_show_stock.js',
            '/hlv_barcode_stock_qty_v3/static/src/css/inline.css',
        ],
        'web.assets_web': [
            '/hlv_barcode_stock_qty_v3/static/src/js/barcode_show_stock.js',
            '/hlv_barcode_stock_qty_v3/static/src/css/inline.css',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
