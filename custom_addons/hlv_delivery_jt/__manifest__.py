# -*- coding: utf-8 -*-
{
    'name': 'HLV J&T Express Integration',
    'version': '1.0',
    'category': 'Inventory/Delivery',
    'summary': 'Integrate J&T Express shipping service with Odoo',
    'description': """
        This module provides integration with J&T Express API for:
        - Creating shipping orders
        - Tracking shipments
        - Webhook status updates
    """,
    'author': 'HLV',
    'depends': ['stock', 'delivery', 'mail', 'hlv_delivery_ghn'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'views/jnt_sync_views.xml',
        'views/res_config_settings_views.xml',
        'views/stock_picking_views.xml',
        'wizard/jt_create_order_wizard_views.xml',
        'wizard/choose_delivery_carrier_wizard_views.xml',
        'wizard/jt_cancel_order_wizard_views.xml',
        'views/jt_print_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
