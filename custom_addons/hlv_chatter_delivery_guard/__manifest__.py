# -*- coding: utf-8 -*-
{
    "name": "HLV Chatter & Delivery Guard",
    "version": "18.0.1.1.0",
    "category": "Inventory",
    "summary": "Prevent chatter message deletion and block outbound delivery by contact",
    "author": "HLV",
    "license": "LGPL-3",
    "depends": ["mail", "contacts", "stock", "sale_stock"],
    "data": [
        "security/security.xml",
        "views/res_partner_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hlv_chatter_delivery_guard/static/src/js/hide_chatter_delete.js",
        ],
    },
    # "installable": True,  # TẠM TẮT ĐỂ BUILD - chặn xóa mail.message gây lỗi test Odoo core
    "installable": False,
    "application": False,
}
