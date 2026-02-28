{
    "name": "Google Ads Automation",
    "version": "1.0",
    "category": "Marketing",
    "summary": "Tích hợp và tự động hóa quảng cáo Google Ads",
    "description": """
        Module tích hợp Google Ads API vào Odoo:
        - Quản lý tài khoản Google Ads API (OAuth2)
        - Đồng bộ chiến dịch
        - (Tương lai) Tự động hóa đánh giá và tối ưu giá thầu.
    """,
    "author": "Your Company",
    "depends": ["base", "mail"],
    "data": [
        "security/google_ads_security.xml",
        "security/ir.model.access.csv",
        "views/google_ads_account_views.xml",
        "views/google_ads_campaign_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}
