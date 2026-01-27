{
    'name': 'Product Label 3x3 (35x22mm)',
    'version': '1.1',
    'summary': 'In tem sản phẩm 3x3 kích thước 35x22mm cho Product Template',
    'description': """
        Module hỗ trợ in tem nhãn sản phẩm kích thước 35x22mm bố cục 3x3.
        Tích hợp vào tính năng In Nhãn chuẩn của Odoo.
        Hỗ trợ in Barcode và QR Code.
    """,
    'category': 'Inventory',
    'author': 'HLV',
    'depends': ['product', 'stock'],
    'data': [
        'data/paper_format.xml',
        'views/product_label_layout_views.xml',
        'report/report_action.xml',
        'report/report_template.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
