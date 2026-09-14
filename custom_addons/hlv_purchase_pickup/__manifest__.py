{
    'name': 'HLV Purchase Pickup',
    'version': '18.0.1.0.0',
    'summary': 'Đi nhận hàng tại nhà cung cấp — đo thời gian di chuyển và thời gian nhận hàng',
    'description': """
Ghi nhật ký hành trình của người đi nhận hàng.

- Quản lý lập chuyến, chọn đơn mua hàng, giao cho một người đi nhận.
- Người đi nhận mở /pickup trên điện thoại, tới từng nhà cung cấp, bấm Đã tới → Đã nhận xong.
- Hệ thống đo: đi từ điểm trước tới đây mất bao lâu, đứng tại nhà cung cấp mất bao lâu.
- Google Maps gợi ý thứ tự đi và giờ dự kiến tới từng điểm.

KHÔNG làm: không xác nhận đơn mua thật, không tạo phiếu kho, không đụng tồn kho, không
đối soát số lượng. Đây là sổ nhật ký hành trình, không phải sổ kho.

Xem kế hoạch chi tiết tại plan/ke-hoach-module-nhan-hang.md
""",
    'category': 'Purchases',
    'author': 'HLV',
    'depends': [
        'purchase',
        'hlv_geo_utils',
        'base_geolocalize',
        'stock',
        'mail',
    ],
    'data': [
        'security/pickup_security.xml',
        'security/ir.model.access.csv',
        'data/pickup_sequence.xml',
        'data/pickup_cron.xml',
        'views/pickup_point_views.xml',
        # Wizard và báo cáo nạp TRƯỚC view chuyến: nút trên form chuyến tham chiếu action của
        # chúng bằng %(...)d, id phải tồn tại sẵn lúc parse.
        'views/pickup_add_po_wizard_views.xml',
        'report/pickup_run_report.xml',
        'views/pickup_run_views.xml',
        'views/pickup_stop_views.xml',
        'views/pickup_line_views.xml',
        'views/purchase_order_views.xml',
        'views/res_config_settings_views.xml',
        'views/pickup_page_templates.xml',
        'views/pickup_menus.xml',
    ],
    'assets': {
        # Thứ tự quan trọng: util -> state/ui -> bản đồ -> app (khởi động sau cùng).
        'hlv_purchase_pickup.assets_pickup_page': [
            'hlv_purchase_pickup/static/src/pickup/pickup.css',
            'hlv_purchase_pickup/static/src/pickup/pickup_utils.js',
            'hlv_purchase_pickup/static/src/pickup/pickup_api.js',
            'hlv_purchase_pickup/static/src/pickup/pickup_map.js',
            'hlv_purchase_pickup/static/src/pickup/pickup_render.js',
            'hlv_purchase_pickup/static/src/pickup/pickup_app.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
