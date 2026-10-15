# -*- coding: utf-8 -*-
{
    "name": "HLV Tra giá nhập cho Sale",
    "summary": "Sale gõ mã / tên hàng để xem giá nhập, NCC, ngày đặt, ngày nhập, SL mua / nhập / trả NCC",
    "description": """
        Một dòng = một dòng đơn mua đã nhập kho (ít nhất một phiếu nhập hoàn tất). SL nhập và SL trả NCC đếm thẳng từ
        phiếu kho đã hoàn tất (không dùng qty_received của Odoo vì phiếu trả không tick
        "Update quantities on SO/PO" thì Odoo không trừ). Nhà cung cấp là công ty gốc
        (commercial partner) của người liên hệ trên đơn mua.
    """,
    "version": "18.0.1.0.0",
    "category": "Sales",
    "author": "HLV",
    "license": "LGPL-3",
    "depends": ["purchase_stock", "sales_team"],
    "data": [
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "views/purchase_price_lookup_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
