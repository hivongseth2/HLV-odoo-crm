# -*- coding: utf-8 -*-
{
    "name": "HLV Chatter & Delivery Guard",
    "version": "18.0.1.0.1",
    "category": "Inventory",
    "summary": "Prevent chatter message deletion and block outbound delivery by contact",
    "author": "HLV",
    "license": "LGPL-3",
    "depends": ["mail", "contacts", "stock", "sale_stock"],
    "data": [
        "views/res_partner_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hlv_chatter_delivery_guard/static/src/js/hide_chatter_delete.js",
        ],
    },
    "installable": True,
    "application": False,
}
