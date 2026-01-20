{
    'name': 'HLV Undelivered Orders Report',
    'version': '1.0',
    'category': 'Inventory',
    'summary': 'Report for undelivered sale orders and move status',
    'description': """
        Module to list undelivered orders, reserved quantities, move line status, 
        and product stock per customer.
    """,
    'author': 'Antigravity',
    'depends': ['sale', 'stock', 'sale_stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/undelivered_report_view.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
