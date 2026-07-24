{
    "name": "HLV - Quản lý Khách hàng thân thiết tập trung",
    "summary": "Centralized Loyalty & Voucher Management cho mô hình đa công ty",
    "description": """
        Quản lý tích điểm, đổi Voucher tập trung tại Công ty Mẹ.
        - Tích điểm tự động khi giao hàng thành công
        - Đổi điểm lấy Voucher (giảm giá cố định / phần trăm)
        - Sử dụng Voucher trên toàn hệ thống (cross-company)
        - Xử lý hoàn hàng / hủy Voucher / hết hạn
    """,
    "version": "18.0.1.7.0",
    "category": "Sales",
    "author": "HLV",
    "depends": ["sale_management", "stock", "mail", "website"],
    "external_dependencies": {
        "python": ["bs4"],
    },
    "data": [
        "security/loyalty_security.xml",
        "security/ir.model.access.csv",
        "data/cron_expire_voucher.xml",
        "data/loyalty_reward_request_sequence.xml",
        "views/res_partner_views.xml",
        "views/menu_views.xml",
        "wizard/redeem_voucher_wizard_views.xml",
        "wizard/loyalty_reset_password_wizard_views.xml",
        "wizard/loyalty_point_adjustment_wizard_views.xml",
        "wizard/loyalty_recalculate_points_wizard_views.xml",
        "views/loyalty_program_views.xml",
        "views/loyalty_voucher_package_views.xml",
        "views/loyalty_history_views.xml",
        "views/loyalty_voucher_views.xml",
        "views/sale_order_views.xml",
        "views/res_config_settings_views.xml",
        "views/loyalty_tier_views.xml",
        "views/loyalty_portal_account_views.xml",
        "views/loyalty_portal_layout.xml",
        "views/loyalty_portal_login.xml",
        "views/loyalty_portal_sections.xml",
        "views/loyalty_portal_dashboard.xml",
        "views/loyalty_portal_dashboard_modals.xml",
        "views/loyalty_portal_result.xml",
        "views/loyalty_portal_history_full.xml",
        "views/loyalty_portal_vouchers_full.xml",
        "views/loyalty_reward_request_views.xml",
        "views/loyalty_portal_redeem.xml",
        "data/loyalty_tier_data.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hlv_loyalty/static/src/css/loyalty_backend.css",
            "hlv_loyalty/static/src/js/loyalty_notifications.js",
        ],
    },
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}