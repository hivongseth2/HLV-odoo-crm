# -*- coding: utf-8 -*-
{
    "name": "HLV Product Merge",
    "version": "18.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Gộp tồn kho của hai sản phẩm và lưu trữ sản phẩm nguồn",
    "author": "HLV",
    "depends": [
        "mail",
        "stock",
        "sale_stock",
        "purchase_stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizard/product_merge_wizard_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
