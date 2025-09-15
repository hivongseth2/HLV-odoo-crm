{
    "name": "HLV Sale Order Preview (Bottom Panel)",
    "version": "1.4.5",
    "summary": "Bottom panel preview for Sale Orders from list view",
    "author": "HLV",
    "license": "LGPL-3",
    "category": "Sales",
    "depends": ["sale", "web_enterprise"],
    "data": [
        "views/sale_order_list_quick.xml"
    ],
    "assets": {
        "web.assets_backend": [
            "hlv_sale_order_preview_bottom_fixed_v145/static/src/js/panel_noqweb.js",
            "hlv_sale_order_preview_bottom_fixed_v145/static/src/scss/panel.scss"
        ]
    },
    "installable": True,
    "application": False
}
