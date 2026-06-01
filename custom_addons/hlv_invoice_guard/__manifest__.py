# -*- coding: utf-8 -*-
{
    "name": "HLV Invoice Guard API",
    "version": "18.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Expose sale/purchase order data for AMIS invoice proposal checks",
    "author": "HLV",
    "license": "LGPL-3",
    "depends": ["base", "sale_management", "purchase", "account"],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
