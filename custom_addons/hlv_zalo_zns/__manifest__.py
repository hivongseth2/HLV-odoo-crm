{
    "name": "HLV Zalo ZNS & Stock Notification",
    "version": "1.0.0",
    "category": "Tools",
    "summary": "Send Zalo ZNS to customers and Stock Notifications to internal staff for warehouse operations",
    "depends": ["stock", "base", "purchase"],
    "data": [
        "security/ir.model.access.csv",
        "views/zns_config_views.xml",
        "views/zalo_shared_token_views.xml",
        "views/zalo_stock_notification_views.xml",
        "data/cron_refresh_shared_token.xml",
        "data/cron_refresh_token.xml",
        "data/cron_refresh_stock_notification_token.xml",
        "data/cron_interaction_reminder.xml"
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
    "external_dependencies": {
        "python": ["requests"]
    }
}
