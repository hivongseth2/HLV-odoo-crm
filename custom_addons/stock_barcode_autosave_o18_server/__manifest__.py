
{
    "name": "Barcode Autosave Odoo 18 (Server-assisted)",
    "summary": "Persist qty_done to server immediately on scan/change using a helper method on stock.picking.",
    "version": "18.0.1",
    "license": "LGPL-3",
    "depends": ["stock_barcode", "stock"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "stock_barcode_autosave_o18_server/static/src/js/autosave_barcode.js"
        ]
    },
    "installable": True
}
