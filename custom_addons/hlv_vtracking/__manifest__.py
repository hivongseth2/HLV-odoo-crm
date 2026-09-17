{
    'name': 'V-Tracking',
    'version': '18.0.1.0.0',
    'summary': 'Theo dõi định vị đội xe qua vTracking Open API — bản đồ trong Odoo và API cho app ngoài',
    'description': """
Bọc toàn bộ vTracking 2.0 Open API (bản 1.0.3) — đúng 2 endpoint nhà cung cấp có:

- POST /api/v1/vtracking/vehicle/search      danh sách xe + vị trí hiện tại
- GET  /api/v1/vtracking/vehicle/journey/:id lịch sử hành trình một xe

Cung cấp:

1. Bản đồ đội xe trong Odoo — vị trí, trạng thái, cảm biến, cảnh báo, tự tải lại.
2. Lịch sử vị trí lưu trong Odoo, có hạn lưu trữ và tác vụ dọn.
3. API đọc cho ứng dụng ngoài, xác thực bằng khoá do Odoo cấp.

Nguyên tắc ranh giới: **chỉ xe bật "Theo dõi vTracking" trong Đội xe mới được đồng bộ,
mới hiện trên bản đồ, mới trả ra API.** Tài khoản vTracking có thể chứa xe của pháp nhân
khác; cờ đó là thứ duy nhất quyết định module này nhìn thấy gì.

Module ĐỘC LẬP: chỉ phụ thuộc Đội xe (fleet) của Odoo. Không dính tới điều phối giao
hàng. Việc nối dữ liệu GPS với kế hoạch giao hàng thuộc về một module cầu nối riêng —
xem plan/ke-hoach-module-vtracking.md.
""",
    'category': 'Human Resources/Fleet',
    'author': 'HLV',
    'depends': ['fleet'],
    'external_dependencies': {'python': ['requests', 'pytz']},
    'data': [
        'security/vtracking_security.xml',
        'security/ir.model.access.csv',
        'data/vtracking_cron.xml',
        'views/fleet_vehicle_views.xml',
        # Nạp trước wizard nhập xe: action của wizard mở list/form xe khai ở file trên.
        'views/vtracking_import_wizard_views.xml',
        'views/vtracking_position_views.xml',
        'views/vtracking_api_key_views.xml',
        # Nạp trước menu: menu trỏ tới action khai trong file này.
        'views/res_company_views.xml',
        'views/vtracking_menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'assets': {
        # Thứ tự quan trọng: util thuần -> bộ nạp thư viện -> component dùng cả hai.
        'web.assets_backend': [
            'hlv_vtracking/static/src/map/vtracking_map.css',
            'hlv_vtracking/static/src/map/vtracking_map_utils.js',
            'hlv_vtracking/static/src/map/vtracking_leaflet_loader.js',
            'hlv_vtracking/static/src/map/vtracking_map.js',
            'hlv_vtracking/static/src/map/vtracking_map.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
