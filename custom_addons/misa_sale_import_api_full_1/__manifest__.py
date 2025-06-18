{
    'name': 'MISA Sale Import via API',
    'version': '1.0',
    'summary': 'Import đơn hàng từ MISA CRM qua API',
    'description': 'Tự động lấy đơn hàng từ MISA CRM và tạo Sale Order trong Odoo',
    'category': 'Sales',
    'author': 'Hoang Long Vu',
    'depends': ['sale', 'base'],
    'data': [
        'security/ir.model.access.csv',
        'views/sale_api_import_wizard_view.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
