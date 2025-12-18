# -*- coding: utf-8 -*-
{
    'name': "HLV Priority Stock Reservation",
    'summary': """
        Automatically unreserve stock from low priority orders (far deadline)
        when a priority order needs stock.
    """,
    'description': """
        This module overrides action_assign to implement a "steal" logic:
        1. When Check Availability is clicked.
        2. If stock is insufficient.
        3. Identify "victim" pickings that have a further `x_studio_hn_giao_hng` date.
        4. Unreserve victims to free up stock.
        5. Assign stock to the current picking.
    """,
    'author': "Antigravity",
    'website': "https://www.example.com",
    'category': 'Inventory/Inventory',
    'version': '1.0',
    'depends': ['stock'],
    'data': [
    ],
    'license': 'LGPL-3',
}
