# -*- coding: utf-8 -*-
{
    "name": "HLV Export Outgoing Picking Excel",
    "summary": "Xuất Excel lệnh xuất kho (stock.picking - outgoing) theo khoảng ngày",
    "version": "18.0.1.0.0",
    "author": "HLV",
    "category": "Inventory/Reporting",
    "license": "LGPL-3",
    "depends": ["stock"],
    "data": [
        "security/ir.model.access.csv",
        "views/picking_export_wizard_views.xml", 
        "views/inventory_report_wizard_views.xml",
        "views/stock_picking_views.xml",
    ],
    "assets": {},
    "installable": True,
    "application": False,
}
