{
    "name": "Stock Pick to Pack Button",
    "version": "16.0.1",
    "depends": ["stock_barcode"],
    "category": "Warehouse",
    "description": "Add button to redirect from done pick to pack in barcode UI",
    "author": "ChatGPT",
    "installable": True,
    "application": False,
    "license": "LGPL-3",
    "assets": {
        "web.assets_backend": [
            "stock_pick_to_pack_button/static/src/js/redirect_pack_button.js"
        ]
    }
}
