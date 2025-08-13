
{
    "name": "Barcode Autosave Odoo 18 (Poller)",
    "summary": "Force-persist scanned lines from Barcode UI via periodic server sync.",
    "version": "18.0.1.2.0",
    "license": "LGPL-3",
    "depends": ["stock_barcode", "stock"],
    "assets": {
        "web.assets_backend": [
            "stock_barcode_autosave_o18_poller/static/src/js/autosave_poller.js"
        ]
    },
    "installable": true
}
