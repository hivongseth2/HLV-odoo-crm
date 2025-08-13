
{
    "name": "Barcode Autosave (Odoo 18)",
    "summary": "Autosave qty_done on scan/change for Barcode app without touching core.",
    "version": "18.1",
    "license": "LGPL-3",
    "installable": True,
    "depends": ["stock_barcode"],
    "assets": {
        "web.assets_backend": [
            "stock_barcode_autosave/static/src/js/autosave_barcode.js"
        ]
    }
}
