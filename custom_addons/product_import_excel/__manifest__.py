{
    'name': 'Product Import Excel',
    'version': '1.0',
    'category': 'Inventory',
    'summary': 'Import products from Excel file',
    'depends': ['product', 'stock'],
    'data': [
        'wizard/product_import_wizard_view.xml',
        'views/product_template_views.xml',
    ],
    'installable': True,
    'application': False,
}