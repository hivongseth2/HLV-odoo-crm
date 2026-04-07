{
    'name': 'HLV - Chặn IP',
    'version': '18.0.1.0.0',
    'summary': 'Chặn truy cập từ các IP độc hại / bot scan',
    'description': """
        Module chặn IP truy cập vào hệ thống Odoo.
        - Quản lý danh sách IP bị chặn
        - Tự động trả về 403 Forbidden cho các IP trong danh sách
        - Hỗ trợ ghi chú lý do chặn
    """,
    'category': 'Tools',
    'author': 'HLV',
    'website': 'https://www.hoanglongvu.com',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'data/blocked_ip_data.xml',
        'views/blocked_ip_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
