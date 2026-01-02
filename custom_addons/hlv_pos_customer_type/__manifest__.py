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
    # Note: Odoo 18 POS uses FormViewDialog from backend for partner editing.
    # The pos_customer_type field is displayed via res_partner_views.xml form inheritance.
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
