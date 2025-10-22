{
    "name": "HLV Viettel Post Integration",
    "summary": "Viettel Post (VTP) API integration: calculate fee, create/cancel orders, webhook updates",
    "version": "18.0.1.0.0",
    "category": "Inventory/Delivery",
    "author": "HLV + ChatGPT",
    "website": "https://hoanglongvu.com",
    "license": "LGPL-3",
    "depends": ["delivery", "base", "stock", "sale_management"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings_view.xml",
        "views/delivery_carrier_view.xml",
        "views/vtp_geo_views.xml",
        'views/stock_picking_vtp_button.xml',
        "wizards/vtp_sync_wizard_views.xml",
        "data/ir_config_parameter.xml",
        'views/stock_picking_vtp_button.xml',
        "data/cron.xml"
    ],
    "assets": {},
    "application": False,
    "installable": True
}
