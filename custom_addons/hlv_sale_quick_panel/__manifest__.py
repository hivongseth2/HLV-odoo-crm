{
    "name": "HLV Sale Quick Panel",
    "summary": "Xem nhanh chi tiết đơn bán trong panel ở dưới màn hình",
    "version": "1.0.0",
    "category": "Sales/Sales",
    "license": "LGPL-3",
    "depends": ["sale", "web"],
    "data": [
        "views/sale_order_views.xml"
    ],
    "assets": {
        "web.assets_backend": [
            "hlv_sale_quick_panel/static/src/js/hlv_quick_panel.js",
            "hlv_sale_quick_panel/static/src/css/hlv_quick_panel.css"
        ]
    },
    "installable": True,
    "application": False
}