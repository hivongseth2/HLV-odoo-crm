{
    'name': 'Product Label 3x3 (35x22mm)',
    'version': '1.0',
    'summary': 'In tem sản phẩm 3x3 kích thước 35x22mm cho Product Template',
    'description': """
        Module hỗ trợ in tem nhãn sản phẩm kích thước 35x22mm bố cục 3x3.
        Hỗ trợ in Barcode và QR Code.
    """,
    'category': 'Inventory',
    'author': 'HLV',
    'depends': ['product', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/label_wizard_view.xml',
        'report/report_action.xml',
        'report/report_template.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
