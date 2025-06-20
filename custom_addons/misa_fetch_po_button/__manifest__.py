{
    'name': 'MISA PO Fetch Button',
    'version': '1.0',
    'depends': ['purchase'],
    'author': 'ChatGPT',
    'category': 'Purchases',
    'description': 'Fetch PO from MISA and create in Odoo',
    'data': [
        'security/ir.model.access.csv',
        'views/misa_po_button_view.xml',
    ],
    'installable': True,
    'auto_install': False,
}
