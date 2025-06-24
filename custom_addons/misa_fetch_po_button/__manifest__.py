{
    'name': 'MISA PO Fetch Button',
    'version': '1.0',
    'depends': ['base','stock','purchase'],
    'author': 'Luan',
    'category': 'Purchases',
    'description': 'Fetch PO from MISA and create in Odoo',
    'data': [
        'security/ir.model.access.csv',
        'views/misa_transfer_button_view.xml',
        'views/misa_po_button_view.xml',
        'views/misa_combined_button_view.xml',
    ],
    'installable': True,
    'auto_install': False,
}
