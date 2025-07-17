{
    "name": "Custom Barcode Scan Redirect",
    "version": "1.0",
    "depends": ["stock", "stock_barcode"],
    "author": "Anh Yêu ❤️",
    "category": "Warehouse",
    "summary": "Scan barcode and redirect to next picking",
    "data": [
        "views/menu.xml",
        "views/scan_ui_template.xml"
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
    'assets': {
        'web.assets_frontend': [
            'custom_barcode_scan_redirect/static/src/js/scan_ui.js',
        ],
    }


}
