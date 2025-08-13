
{
    "name": "Barcode Autosave Odoo 18 (Fix)",
    "summary": "Autosave qty_done on scan/change for Barcode app without touching core.",
    "version": "18.0.1.0.1",
    "license": "LGPL-3",
    "installable": true,
    "depends": ["stock_barcode"],
    "assets": {
        "web.assets_backend": [
            "stock_barcode_autosave_o18_fix/static/src/js/autosave_barcode.js"
        ]
    }
}
