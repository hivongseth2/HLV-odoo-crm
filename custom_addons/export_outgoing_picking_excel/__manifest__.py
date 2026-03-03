# -*- coding: utf-8 -*-
{
    "name": "HLV Export Outgoing Picking & Purchase Order Excel",
    "summary": "Xuất Excel lệnh xuất kho (stock.picking - outgoing) và đơn mua hàng theo khoảng ngày",
    "version": "18.0.1.0.0",
    "author": "HLV",
    "category": "Inventory/Reporting",
    "license": "LGPL-3",
    "depends": ["stock", "purchase", "sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/picking_export_wizard_views.xml", 
        "views/inventory_report_wizard_views.xml",
        "views/purchase_export_wizard_views.xml",
        "views/picking_export_shopee_wizard_views.xml",
        "views/stock_export_wizard_views.xml",
        "views/out_return_report_wizard_views.xml",
        "views/sales_report_export_wizard_views.xml",
        "views/stock_picking_views.xml",
    ],
    "assets": {},
    "installable": True,
    "application": False,
}

