{
    "name": "HLV Purchase Product Origin",
    "version": "18.0.1.0.0",
    "summary": "STT và xuất xứ hàng hóa trên đơn mua, lô và tồn kho",
    "category": "Purchases/Purchases",
    "author": "HLV",
    "license": "LGPL-3",
    "depends": ["purchase_stock"],
    "data": [
        "views/purchase_order_views.xml",
        "views/stock_lot_views.xml",
        "views/stock_quant_views.xml",
        "report/purchase_order_report.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
