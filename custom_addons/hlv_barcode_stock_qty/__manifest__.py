# -*- coding: utf-8 -*-
{
    'name': 'HLV Barcode Stock Quantity',
    'version': '1.0',
    'summary': 'Hiển thị tồn kho khi quét mã vạch trong ứng dụng Barcode',
    'author': 'Hoang Long Vu - Thành Luân',
    'category': 'Inventory/Barcode',
    'depends': ['stock', 'stock_barcode'],
    'data': [],
    'assets': {
        'web.assets_backend': [
            '/hlv_barcode_stock_qty/static/src/js/barcode_show_stock.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
