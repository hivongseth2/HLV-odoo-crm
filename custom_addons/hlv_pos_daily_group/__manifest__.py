# -*- coding: utf-8 -*-
{
    'name': 'HLV POS Daily Group',
    'version': '1.0',
    'category': 'Point of Sale',
    'summary': 'Auto-fill POS Group with daily value',
    'description': """
        This module automatically populates the x_studio_pos_group field 
        on pos.order with a value in the format POS/ddmmyy based on the order date.
    """,
    'author': 'Antigravity',
    'depends': ['point_of_sale'],
    'data': [
        'data/ir_actions_server.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
