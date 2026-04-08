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
    'depends': ['stock', 'delivery', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'data/ir_cron_data.xml',
        'views/jnt_sync_views.xml',
        'views/res_config_settings_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_warehouse_views.xml',
        'views/jt_monitor_views.xml',
        'views/delivery_sender_address_views.xml',
        'wizard/jt_create_order_wizard_views.xml',
        'wizard/choose_delivery_carrier_wizard_views.xml',
        'wizard/jt_cancel_order_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_delivery_jt/static/src/js/jt_print.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
