# -*- coding: utf-8 -*-
{
    'name': "Shopee Webhook Integration",
    'summary': """
        Receive delivery status updates from Shopee via Webhook""",
    'description': """
        This module adds a webhook endpoint to receive delivery status updates from Shopee.
        It updates the 'shopee_delivery_status' field on the Sale Order based on the 'shopee_order_ref'.
    """,
    'author': "HLV",
    'website': "https://www.hlv.vn",
    'category': 'Sales',
    'version': '0.1',
    'depends': ['sale', 'hlv_zalo_zns', 'shopee_order_fetch'],
    'data': [
        'data/cron_data.xml',
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
