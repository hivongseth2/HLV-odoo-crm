{
    "name": "HLV Purchase Order Line Custom Fields",
    "version": "18.0.1.0.0",
    "summary": "Bổ sung STT tự động, Năm sản xuất và Xuất xứ cho chi tiết đơn mua hàng (PO Line)",
    "category": "Purchases",
    "author": "HLV",
    "license": "LGPL-3",
    "depends": ["purchase", "stock", "purchase_stock"],
    "data": [
        "views/purchase_order_views.xml",
        "views/stock_picking_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
