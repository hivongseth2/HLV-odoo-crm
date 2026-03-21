{
    'name': 'HLV MISA Product Import',
    'version': '2.0',
    'depends': ['base', 'product', 'website', 'misa_fetch_po_button'],
    'author': 'HLV',
    'category': 'Inventory',
    'description': 'Import sản phẩm từ MISA CRM vào Odoo theo mã sản phẩm',
    'data': [
        'views/templates.xml',
    ],
    'installable': True,
    'auto_install': False,
}
