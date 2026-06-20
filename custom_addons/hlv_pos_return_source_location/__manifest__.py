# -*- coding: utf-8 -*-
{
    'name': 'HLV POS Return to Source Location',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Returned items in POS go back to their original source location.',
    'author': 'HLV',
    'depends': ['point_of_sale', 'stock'],
    'data': [],
    'assets': {
        'point_of_sale._assets_pos': [
            'hlv_pos_return_source_location/static/src/xml/source_location_popup.xml',
            'hlv_pos_return_source_location/static/src/js/source_location_button.js',
            'hlv_pos_return_source_location/static/src/css/source_location.css',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
