{
    'name': 'HLV - Admin giữ khoá 2FA',
    'version': '18.0.1.0.0',
    'summary': 'Chỉ nhóm "Admin bảo mật 2FA" bật / tắt / xem khoá 2FA của nhân viên',
    'description': """
        - Mọi người khác không còn nút bật / tắt 2FA (cả trong Preferences lẫn form user); server cũng chặn.
        - Nhóm này có nút "Cấp 2FA" (tạo khoá cho user) và "Xem khoá 2FA" (hiện QR + khoá + mã 6 số hiện tại).
        - Mỗi lần cấp / xem đều ghi vào chatter của user và log, để còn dấu vết ai đã lấy khoá.
    """,
    'category': 'Administration',
    'author': 'HLV',
    'depends': ['auth_totp'],
    'data': [
        'security/hlv_totp_admin_groups.xml',
        'security/ir.model.access.csv',
        'views/res_users_views.xml',
        'wizard/totp_secret_view_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
