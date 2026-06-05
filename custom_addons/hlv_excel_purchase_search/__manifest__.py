# -*- coding: utf-8 -*-

{
    "name": "HLV Tra Cứu Excel Mua Hàng",
    "summary": "Upload Excel sổ chi tiết mua hàng và tra cứu công khai theo từ khóa.",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "author": "HLV",
    "license": "LGPL-3",
    "depends": ["base", "website"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/excel_purchase_file_views.xml",
        "views/templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "hlv_excel_purchase_search/static/src/css/excel_purchase_search.css",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
