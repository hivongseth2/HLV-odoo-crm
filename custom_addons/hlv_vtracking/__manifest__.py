{
    'name': 'V-Tracking',
    'version': '18.0.1.3.0',
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

4. Kế hoạch giao hàng theo xe · buổi · ngày, có cụm tuyến, định mức thời gian, thói quen
   khách và vòng đối chiếu kế hoạch ↔ thực tế.

Ban đầu module này độc lập hoàn toàn với điều phối giao hàng. Nay nó đã ôm luôn phần lập
kế hoạch, nên phụ thuộc thêm sale_stock, purchase_stock và hlv_barcode_shipper — xem lý do
ở từng dòng trong `depends`.
""",
    'category': 'Human Resources/Fleet',
    'author': 'HLV',
    'depends': [
        'fleet',
        # base_geolocalize chỉ dùng như service tra toạ độ (base.geocoder) — không dùng
        # partner_latitude/longitude của nó, vì toạ độ phải nằm ở ĐỊA ĐIỂM chứ không ở
        # từng mã đối tác (nhiều mã khách thường trỏ về cùng một địa chỉ vật lý).
        'base_geolocalize',
        # Addon thuần hàm (không model/view/controller). Đọc chuỗi toạ độ dán tay và đo
        # khoảng cách phải cho ra CÙNG kết quả ở mọi module HLV — điều phối giao hàng và
        # đi nhận hàng đã dùng chung nó.
        'hlv_geo_utils',
        # Phiếu giao (stock.picking) là đơn vị xếp lên xe. sale_stock để có picking.sale_id
        # và để xếp được ĐƠN BÁN vào kế hoạch khi kho chưa soạn hàng, phiếu xuất chưa có.
        'sale_stock',
        # Phiếu yêu cầu gửi AI do người bán hàng tạo: cần nhóm quyền của sale để phân
        # quyền đúng, và menu Thao tác trên đơn bán để họ gửi mà không rời màn đang làm.
        'sales_team',
        # API cho AI lập kế hoạch cần biết hàng của đơn bán đã VỀ chưa: đơn mua nối với
        # đơn bán qua purchase.order.origin, và số đã nhận nằm ở purchase_stock.
        'purchase_stock',
        # Nguồn THỰC TẾ của vòng đối chiếu: shipper_receive_time (lúc hàng lên xe),
        # shipper_returned + shipper_return_reason (giao hụt). Phụ thuộc CỨNG chứ không
        # đọc mềm qua `_fields` như với field Studio: đối chiếu kế hoạch với thực tế là
        # tính năng cốt lõi, đọc mềm chỉ khiến mọi ô thực tế rỗng mà không ai biết vì sao.
        'hlv_barcode_shipper',
    ],
    'external_dependencies': {'python': ['requests', 'pytz']},
    'data': [
        'security/vtracking_security.xml',
        'security/ir.model.access.csv',
        'data/vtracking_place_type_data.xml',
        'data/vtracking_zone_data.xml',
        'data/vtracking_cron.xml',
        'views/fleet_vehicle_views.xml',
        # Nạp trước wizard nhập xe: action của wizard mở list/form xe khai ở file trên.
        'views/vtracking_import_wizard_views.xml',
        'views/vtracking_zone_views.xml',
        'views/vtracking_place_views.xml',
        'views/vtracking_partner_profile_views.xml',
        'views/vtracking_place_import_views.xml',
        'views/vtracking_rule_import_views.xml',
        'views/vtracking_plan_views.xml',
        'views/vtracking_plan_add_views.xml',
        'views/vtracking_calibration_views.xml',
        'views/vtracking_ai_request_views.xml',
        'views/vtracking_sale_board_templates.xml',
        'report/vtracking_plan_report.xml',
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
            # Bộ giải mã polyline: biến toàn cục, dùng chung với trang /giao-hang
            # (xem đầu file vì sao không phải module) — phải nạp trước file vẽ lộ trình.
            'hlv_vtracking/static/src/map/vtracking_polyline_codec.js',
            'hlv_vtracking/static/src/map/vtracking_map_places.js',
            'hlv_vtracking/static/src/map/vtracking_map_route.js',
            'hlv_vtracking/static/src/map/vtracking_leaflet_loader.js',
            'hlv_vtracking/static/src/map/vtracking_plan_table.js',
            'hlv_vtracking/static/src/map/vtracking_plan_table.xml',
            'hlv_vtracking/static/src/map/vtracking_map.js',
            'hlv_vtracking/static/src/map/vtracking_map.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
