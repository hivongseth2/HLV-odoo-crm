{
    'name': 'HLV - Duyệt đăng nhập theo thiết bị',
    'version': '18.0.1.0.0',
    'summary': 'User nội bộ đăng nhập từ thiết bị mới phải chờ admin duyệt',
    'description': """
        - Mỗi trình duyệt được gắn một cookie thiết bị. Lần đầu user nội bộ đăng nhập
          (đúng mật khẩu) từ thiết bị đó sẽ bị chặn và tạo yêu cầu duyệt.
        - Admin (nhóm Settings) nhận email, vào Thiết lập > Người dùng > Duyệt thiết bị
          đăng nhập để Duyệt / Từ chối.
        - Duyệt có hạn (mặc định 30 ngày, tham số hlv_login_approval.valid_days).
        - Không áp dụng cho admin, user portal, và XML-RPC / API key.
    """,
    'category': 'Administration',
    'author': 'HLV',
    'website': 'https://www.hoanglongvu.com',
    'depends': ['mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'data/mail_template_data.xml',
        'views/hlv_login_device_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
