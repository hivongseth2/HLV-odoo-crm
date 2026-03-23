# hlv_barcode_shipper/__manifest__.py
# -*- coding: utf-8 -*-

{
    "name": "HLV Barcode Shipper",
    "summary": "Mobile barcode screen for shipper to scan PICK -> OUT",
    "version": "18.0.3.12.0",
    "author": "Hoang Long Vu",
    "website": "https://hoanglongvu.com",
    "category": "Inventory/Barcode",
    "license": "OPL-1",
    "depends": ["stock", "web"],
    "pre_init_hook": "pre_init_hook",
    "data": [
        "security/hlv_barcode_shipper_security.xml",
        "security/ir.model.access.csv",
        "views/barcode_scan_log_views.xml",
        "views/stock_picking_views.xml",
        "views/barcode_shipper_views.xml",
        "views/res_config_settings_views.xml",
        "views/shipper_management_views.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "hlv_barcode_shipper/static/src/css/barcode_shipper.css",
            "hlv_barcode_shipper/static/src/js/barcode_scanner.js",
        ],
    },
    "installable": True,
    "application": True,
}

