# -*- coding: utf-8 -*-
{
    'name': 'HLV POS Return to Original Source Location',
    'version': '18.0.1.0.0',
    'summary': 'Ensures POS refunds return products to their original shipping location.',
    'description': """
        This module overrides the default POS return behavior to route refunded products
        back to the exact stock location from which they were originally shipped.
    """,
    'author': 'Antigravity',
    'category': 'Point of Sale',
    'depends': ['point_of_sale', 'stock'],
    'data': [],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
