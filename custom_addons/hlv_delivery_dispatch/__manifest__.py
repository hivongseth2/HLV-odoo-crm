{
    'name': 'HLV Delivery Dispatch',
    'version': '18.0.1.0.0',
    'summary': 'Điều phối chuyến giao hàng — sale xem kế hoạch và đăng ký chuyến',
    'description': """
Điều phối giao hàng theo CHUYẾN (trip) và ĐIỂM GIAO (point).

- Điều phối: xếp đơn vào chuyến theo cụm tuyến, publish kế hoạch ngày.
- Sale: xem kế hoạch đã publish tại /delivery_plan, đăng ký chuyến cho đơn của mình.
- Nền dữ liệu: cụm tuyến, điểm giao (gom nhiều mã khách về 1 điểm vật lý), thói quen khách.

Xem kế hoạch chi tiết tại plan/ke-hoach-module-dieu-phoi.md
""",
    'category': 'Sales',
    'author': 'HLV',
    'depends': [
        'hlv_sale_delivery_planning',
        'fleet',
        'base_geolocalize',
        'stock',
        'mail',
    ],
    'data': [
        'security/dispatch_security.xml',
        'security/ir.model.access.csv',
        'data/dispatch_cron.xml',
        'views/delivery_zone_views.xml',
        'views/delivery_point_views.xml',
        'views/delivery_partner_profile_views.xml',
        'views/delivery_plan_day_views.xml',
        'views/delivery_trip_views.xml',
        'views/delivery_trip_registration_views.xml',
        'views/delivery_profile_task_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/stock_warehouse_views.xml',
        'views/res_users_views.xml',
        'views/dispatch_import_views.xml',
        'views/dispatch_page_templates.xml',
        'views/dispatch_menus.xml',
    ],
    'assets': {
        'hlv_delivery_dispatch.assets_dispatch_page': [
            'hlv_delivery_dispatch/static/src/dispatch_page/dispatch_page.css',
            'hlv_delivery_dispatch/static/src/dispatch_page/dispatch_page.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
