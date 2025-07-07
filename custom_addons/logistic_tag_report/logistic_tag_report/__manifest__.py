
{
    'name': 'Logistic Tag Report',
    'version': '16.0.1.0.0',
    'summary': 'Print Logistic Tag for each move line',
    'depends': ['stock'],
    'data': [
        'report/logistic_tag_report.xml',
        'views/stock_picking_view.xml',
    ],
    'installable': True,
    'application': False,
}
