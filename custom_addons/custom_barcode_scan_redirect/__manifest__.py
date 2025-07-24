
{
    "name": "Custom Barcode Pack Scan",
    "version": "1.0",
    "depends": ["stock", "stock_barcode"],
    "author": "Anh Yêu",
    "category": "Warehouse",
    "summary": "Scan từng sản phẩm trong phiếu Pack bằng barcode",
    "data": [
        "views/pack_scan_template.xml"
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
    "assets": {
        "web.assets_frontend": [
            "custom_barcode_pack_scan/static/src/js/scan_pack.js"
        ]
    }
}
