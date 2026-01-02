# -*- coding: utf-8 -*-
{
    'name': 'HLV POS Customer Type',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Add Customer Type selection to POS Partner Details',
    'description': """
        Module adds a selection field 'Customer Type' (Loại khách hàng)
        to res.partner and displays it in the POS Customer creation/edit screen.
    """,
    'author': 'HLV',
    'depends': [
        'point_of_sale',
        'contacts',
    ],
    'data': [
        'views/res_partner_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'hlv_pos_customer_type/static/src/xml/partner_details.xml',
            'hlv_pos_customer_type/static/src/js/debug_partner.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
