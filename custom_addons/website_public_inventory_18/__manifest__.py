# -*- coding: utf-8 -*-
{
    "name": "Website Public Inventory (Odoo 18)",
    "summary": "Public inventory lookup and order lookup pages with search & pagination.",
    "version": "18.0.1.0.0", 
    "author": "Your Company",
    "website": "https://example.com",
    "category": "Website/Inventory",
    "license": "LGPL-3",
    "depends": ["website", "stock", "sale", "mrp", "misa_fetch_po_button"],
    "data": [
        "views/templates.xml",
        "views/order_lookup_templates.xml",
        "views/menu.xml",
        "views/res_config_settings_views.xml",
        "views/chatbot_templates.xml",
        "views/misa_purchase_lookup.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "website_public_inventory_18/static/src/css/order_lookup.css",
            "website_public_inventory_18/static/src/css/chatbot.css",
            "website_public_inventory_18/static/src/css/misa_lookup.css",
            "website_public_inventory_18/static/src/js/chatbot.js",
        ],
    },
    "installable": True,
    "application": False,
}

