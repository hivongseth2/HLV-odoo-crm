# -*- coding: utf-8 -*-
{
    "name": "Import tồn kho theo vị trí",
    "version": "1.0",
    "category": "Inventory",
    "summary": "Import tồn kho theo từng vị trí cho sản phẩm",
    "author": "ChatGPT",
'depends': ['base', 'stock'],
    "data": [
        "views/import_stock_quant_wizard_view.xml",
        "security/ir.model.access.csv",
        "menu/menu.xml"
    ],
    "installable": True,
    "application": False,
}
