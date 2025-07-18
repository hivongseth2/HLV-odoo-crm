# -*- coding: utf-8 -*-
{
    'name': 'Stock Picking Barcode Next Group',
    'version': '0.1',
    'category': 'Inventory',
    'summary': 'Auto navigate to next picking in group after done in Barcode UI',
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
