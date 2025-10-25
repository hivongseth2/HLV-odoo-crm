{
    'name': 'MISA Return Import',
    'version': '1.0',
    'depends': ['base', 'stock', 'purchase', 'misa_fetch_po_button'],
    'author': 'HLV',
    'category': 'Inventory',
    'description': 'Import phiếu trả hàng từ MISA về dưới dạng phiếu nhập kho',
    'data': [
        'security/ir.model.access.csv',
        'views/misa_return_import_view.xml',
    ],
    'installable': True,
    'auto_install': False,
}
