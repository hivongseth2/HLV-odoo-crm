{
    'name': 'HLV - Chặn IP & Chống Bot',
    'version': '18.0.3.0.0',
    'summary': 'Tự động phát hiện và chặn bot scan / IP độc hại',
    'description': """
        Module chặn IP và tự động phát hiện bot scan.
        - Tự động phát hiện bot qua path đáng ngờ (.php, .asp, /etc/passwd, wp-admin...)
        - Tự động chặn IP vượt quá rate limit (>120 req/phút)
        - Quản lý danh sách IP bị chặn & whitelist
        - Redirect IP bị chặn sang google.com
        - Đếm số lần chặn, flush xuống DB định kỳ (không hit DB mỗi request)
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
