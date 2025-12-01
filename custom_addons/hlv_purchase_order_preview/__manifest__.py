{
    "name": "HLV Purchase Order Preview & Filters",
    "version": "1.0.0",
    "summary": "Quick preview, status filters, and product search for Purchase Orders",
    "author": "HLV",
    "license": "LGPL-3",
    "category": "Purchases",
    "depends": ["purchase", "purchase_stock", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/purchase_order_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hlv_purchase_order_preview/static/src/js/po_preview_panel.js",
            "hlv_purchase_order_preview/static/src/scss/po_preview_panel.scss",
        ]
    },
    "installable": True,
    "application": False,
}
