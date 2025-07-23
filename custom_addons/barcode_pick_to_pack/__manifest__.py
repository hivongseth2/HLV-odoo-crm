{
    "name": "Barcode Pick to Pack (JS Override)",
    "version": "0.1",
    "category": "Stock",
    "depends": ["stock_barcode"],

    "installable": True,
    "application": False,
    "assets": {
    "web.assets_backend": [
        "barcode_pick_to_pack/static/src/js/barcode_picking_redirect.js",
    ],
}

}
