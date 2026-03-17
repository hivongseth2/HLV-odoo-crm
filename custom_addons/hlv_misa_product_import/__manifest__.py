{
    'name': 'HLV MISA Product Import',
    'version': '1.1',
    'depends': ['base', 'product', 'point_of_sale', 'misa_fetch_po_button'],
    'author': 'HLV',
    'category': 'Inventory',
    'description': 'Import sản phẩm từ MISA CRM vào Odoo theo mã sản phẩm',
    'data': [
        'security/ir.model.access.csv',
        'views/misa_product_import_views.xml',
    ],
    'installable': True,
    'auto_install': False,
}
