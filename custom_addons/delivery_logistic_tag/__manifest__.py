{
    'name': 'Delivery Logistic Tag',
    'version': '1.0',
    'category': 'Inventory',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_picking_views.xml',
        'report/report_logistic_tag.xml',
    ],
    'installable': True,
    'application': False,
}