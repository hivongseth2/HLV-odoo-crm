{
    'name': 'MISA PO Fetch Button',
    'version': '1.1',
    'depends': ['base', 'stock', 'purchase', 'sale', 'website'],
    'author': 'Luan',
    'category': 'Purchases',
    'description': 'Fetch PO from MISA and create in Odoo',
    'data': [
        'security/ir.model.access.csv',
        'views/misa_transfer_button_view.xml',
        'views/misa_po_button_view.xml',
        'views/misa_po_sync_view.xml',
        'views/misa_combined_button_view.xml',
        'views/misa_return_button_view.xml',
        'views/sale_order_misa_sync.xml',
        'views/product_view.xml',
        'views/misa_purchase_lookup.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'misa_fetch_po_button/static/src/css/misa_lookup.css',
        ],
    },
    'python': [
        'models/sale_api_import_wizard.py',
    ],
    'installable': True,
    'auto_install': False,
}
