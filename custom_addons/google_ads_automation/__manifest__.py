{
    "name": "Google Ads Automation",
    "version": "18.0.2.0.3",
    "category": "Marketing",
    "summary": "Tích hợp và tự động hóa quảng cáo Google Ads dựa trên tồn kho & lợi nhuận",
    "description": """
        Module tích hợp Google Ads API vào Odoo:
        - Quản lý tài khoản Google Ads API (OAuth2)
        - Đồng bộ chiến dịch, nhóm quảng cáo, mẫu quảng cáo
        - Product Feed: Liên kết sản phẩm ↔ campaign
        - Strategy: Tự động sinh rules dựa trên tồn kho, biên lợi nhuận, hiệu suất
        - Mutate API: Gửi lệnh pause/enable/adjust lên Google Ads
    """,
    "author": "HLV",
    "depends": ["base", "mail", "stock", "sale"],
    "data": [
        "security/google_ads_security.xml",
        "security/ir.model.access.csv",
        "data/google_ads_ad_type_data.xml",
        "data/google_ads_ad_group_type_data.xml",
        "data/ir_cron_data.xml",
        "wizard/google_ads_product_feed_wizard_views.xml",
        "wizard/google_ads_adsroid_chat_views.xml",
        "views/google_ads_account_views.xml",
        "views/google_ads_campaign_views.xml",
        "views/google_ads_ad_group_views.xml",
        "views/google_ads_ad_views.xml",
        "views/google_ads_product_feed_views.xml",
        "views/google_ads_strategy_views.xml",
        "views/google_ads_rule_views.xml",
        "views/google_ads_conversion_views.xml",
        "views/google_ads_conversion_action_views.xml",
        "views/google_ads_tag_views.xml",
        "views/google_ads_adsroid_log_views.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "google_ads_automation/static/src/css/premium_dashboard.css",
        ],
    },
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}
