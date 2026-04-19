# -*- coding: utf-8 -*-
{
    "name": "RapidS1: Odoo Barcode App | Barcode | Barcode Scanner | Odoo Scanner | DSCSA | Scanner | Edge Scanner | Warehouse | Supply Chain | Inventory | Inventory Scanner | Warehouse Scanner | Shipping",
    "version": "0.0",
    "category": "Warehouse",
    "summary": """Best in class mobile warehouse barcode scanner for Odoo. This is for a warehouse management mobile app with smart barcode scanning feature. Just place it into the add-ons path and you're ready to go!""",
    "description": """This is for a warehouse management mobile app with smart barcode scanning feature. Just place it into the add-ons path and you're ready to go!""",
    "depends": ["base", "sale_management", "account", "stock", "purchase", "web"],
    "data": ["security/ir.model.access.csv", "views/product_template_custom_views.xml", "wizard/middleware_confirm_wizard_view.xml"],
    "assets": {
        "web.assets_backend": ["web/static/src/legacy/js/core/*", "web/static/src/legacy/xml/*", "middleware_rest_controller/static/src/js/middleware.js"],
    },
    "images": ["static/description/banner.jpg"],
    "license": "LGPL-3",
    "author": "TrackTraceRX",
    "company": "TrackTraceRX",
    "maintainer": "TrackTraceRX",
    "website": "https://www.tracktracerx.com/rapids1-en",
}
