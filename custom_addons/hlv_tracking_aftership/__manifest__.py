{
    'name': 'HLV Tracking AfterShip',
    'version': '1.0.0',
    'summary': 'Tra cứu vận đơn AfterShip cho khách hàng HLV',
    'category': 'Website',
    'depends': ['website', 'stock', 'sale'],
    'data': [
        'views/website_tracking_templates.xml',
        'views/stock_picking_views.xml',
        'views/sale_order_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'hlv_tracking_aftership/static/src/scss/tracking.scss',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
