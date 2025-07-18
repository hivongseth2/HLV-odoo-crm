# -*- coding: utf-8 -*-
{
    'name': 'Stock Barcode Auto Next Picking HLV',
    'version': '0.1',
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
            'stock_picking_barcode_next_group/static/src/js/barcode_picking_override.js',
        ],
    },
}
