{
    "name": "HLV Mobile Barcode Scanner",
    "version": "18.0.1.0.0",
    "category": "Inventory",
    "summary": "Mobile-optimized barcode scanning application for warehouse operations",
    "description": """
Mobile Barcode Scanner
======================
- Smart Routing Scan (Auto detect Picking/Product/Location/Package)
- Mobile-optimized UI with OWL
- Support Picking, Internal Transfer, Location Moves, Put in Pack
    """,
    "author": "HLV",
    "depends": ["base", "stock", "web"],
    "data": [
        "views/res_config_settings_views.xml",
        "views/barcode_menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hlv_mobile_barcode/static/src/css/barcode_mobile.css",
            "hlv_mobile_barcode/static/src/components/**/*.js",
            "hlv_mobile_barcode/static/src/components/**/*.xml",
        ],
    },
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}
