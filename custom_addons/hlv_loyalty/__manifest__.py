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
    "version": "18.0.1.0.0",
    "category": "Sales",
    "author": "HLV",
    "depends": ["sale_management", "stock", "mail", "website"],
    "data": [
        "security/loyalty_security.xml",
        "security/ir.model.access.csv",
        "data/cron_expire_voucher.xml",
        "wizard/redeem_voucher_wizard_views.xml",
        "views/loyalty_program_views.xml",
        "views/loyalty_voucher_package_views.xml",
        "views/loyalty_history_views.xml",
        "views/loyalty_voucher_views.xml",
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
        "views/res_config_settings_views.xml",
        "views/loyalty_tier_views.xml",
        "views/loyalty_public_templates.xml",
        "views/menu_views.xml",
        "data/loyalty_tier_data.xml",
    ],
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}
