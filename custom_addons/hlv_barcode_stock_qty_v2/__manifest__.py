# -*- coding: utf-8 -*-
{
    'name': 'HLV Barcode Stock Quantity (v2)',
    'version': '1.1',
    'summary': 'Hiển thị tồn kho khi quét barcode trong màn hình phiếu & menu barcode',
    'author': 'HLV - Thanh Luan',
    'category': 'Inventory/Barcode',
    'depends': ['stock', 'stock_barcode'],
    'data': [],
    'assets': {
        'web.assets_backend': [
            '/hlv_barcode_stock_qty_v2/static/src/js/barcode_show_stock.js',
        ],
        'web.assets_web': [
            '/hlv_barcode_stock_qty_v2/static/src/js/barcode_show_stock.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
