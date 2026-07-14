# -*- coding: utf-8 -*-
{
    "name": "HLV Chatter & Delivery Guard",
    "version": "18.0.1.0.0",
    "category": "Inventory",
    "summary": "Prevent chatter message deletion and block outbound delivery by contact",
    "author": "HLV",
    "license": "LGPL-3",
    "depends": ["mail", "contacts", "stock", "sale_stock"],
    "data": [
        "views/res_partner_views.xml",
    ],
    "installable": True,
    "application": False,
}
