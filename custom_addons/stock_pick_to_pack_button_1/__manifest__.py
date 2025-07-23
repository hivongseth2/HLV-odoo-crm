{
    "name": "Stock Barcode Redirect to Pack",
    "version": "16.0.1",
    "license": "LGPL-3",
    "category": "Inventory",
    "depends": ["stock_barcode",'web', 'stock'],
    "data": [
        "views/assets.xml"
    ],
    'assets': {
        'web.assets_backend': [
            'stock_pick_to_pack_button_1/static/src/js/redirect_to_pack.js',
        ],
    },

    "installable": True,
    "application": False
}