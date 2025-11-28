# -*- coding: utf-8 -*-
{
    'name': 'Sale Order Partner Domain',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Custom domain for partner_shipping_id and partner_invoice_id in Sale Order',
    'description': """
        This module overrides the domain of partner_shipping_id and partner_invoice_id
        to allow selecting both 'contact' and 'delivery' type partners.
    """,
    'author': 'HLV',
    'depends': ['sale'],
    'data': [
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
