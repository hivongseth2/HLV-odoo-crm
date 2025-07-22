{
    "name": "Custom Barcode Scan Redirect",
    "version": "1.2",
    "category": "Warehouse",
    "summary": "Custom UI for scanning barcodes with in-place handling",
    "author": "anh yêu",
    "depends": ["stock", "stock_barcode", "web"],
    "data": [
        "views/scan_template.xml",
        "views/menu.xml"
    ],
    "assets": {
        "web.assets_backend": [
            "/custom_barcode_scan_redirect/static/src/js/scan_ui.js"
        ]
    },
    "installable": true,
    "application": false
}
