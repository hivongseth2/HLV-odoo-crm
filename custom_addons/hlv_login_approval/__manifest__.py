{
    'name': 'HLV - Duyệt đăng nhập theo thiết bị',
    'version': '18.0.3.0.0',
    'summary': 'User nội bộ đăng nhập từ thiết bị mới phải chờ admin duyệt',
    'description': """
        - Mỗi trình duyệt được gắn một cookie thiết bị. Lần đầu user nội bộ đăng nhập
          (đúng mật khẩu) từ thiết bị đó sẽ vào trang chờ và tạo yêu cầu duyệt.
        - Admin duyệt xong, trang chờ nhận tín hiệu qua bus (websocket) và tự vào hệ thống.
        - Nhóm "Người duyệt thiết bị đăng nhập" nhận email và Duyệt / Từ chối tại
          Thiết lập > Người dùng & Công ty > Duyệt thiết bị đăng nhập. Không ai tự duyệt
          thiết bị của chính mình.
        - Áp dụng cho mọi user nội bộ, kể cả admin. Ngoại lệ duy nhất là tài khoản cứu hộ
          (base.user_admin) khi đã bật 2FA: không chờ duyệt nhưng máy mới vẫn báo người duyệt.
        - Duyệt có hạn (mặc định 30 ngày, tham số hlv_login_approval.valid_days).
        - Không áp dụng cho user portal và XML-RPC / API key.
    """,
    'category': 'Administration',
    'author': 'HLV',
    'website': 'https://www.hoanglongvu.com',
    'depends': ['mail', 'auth_totp'],
    'data': [
        'security/hlv_login_approval_groups.xml',
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'data/mail_template_data.xml',
        'views/hlv_login_device_views.xml',
        'views/login_wait_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'hlv_login_approval/static/src/js/login_wait.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
