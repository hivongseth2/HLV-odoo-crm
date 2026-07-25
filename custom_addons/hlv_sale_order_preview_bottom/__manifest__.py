
{
    "name": "HLV Sale Order Preview (Bottom Panel)",
    "version": "1.3.0",
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
            "hlv_sale_order_preview_bottom/static/src/js/panel_noqweb.js",
            "hlv_sale_order_preview_bottom/static/src/scss/panel.scss"
        ]
    },
    # "installable": True,  # TẠM TẮT - ĐÃ CÓ MODULE FIXED v145
    "installable": False,
    "application": False
}
