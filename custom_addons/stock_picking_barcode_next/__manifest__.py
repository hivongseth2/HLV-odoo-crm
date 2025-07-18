# -*- coding: utf-8 -*-
{
    'name': 'Stock Barcode Auto Next Picking',
    'version': '16.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Auto switch to next picking after done in Odoo Barcode',
    'author': 'anh yêu ❤️',
    'license': 'LGPL-3',
    'depends': ['stock_barcode'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'assets': {
        'web.assets_backend': [
            'stock_barcode_auto_next/static/src/js/barcode_picking_override.js',
        ],
    },
}
