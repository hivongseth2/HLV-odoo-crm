# -*- coding: utf-8 -*-
{
    "name": "Return Sale Request",
    "version": "18.0.1.0.0",
    "summary": "Quản lý đề nghị trả hàng bán từ khách hàng về nhà cung cấp",
    "description": """
        Module xử lý quy trình trả hàng từ khách hàng về nhà cung cấp.
        Tích hợp với MISA CRM để đồng bộ đề nghị trả hàng.
        Flow: CRM MISA → Odoo → Phiếu nhập kho (từ customer) → Phiếu xuất kho (về vendor)
    """,
    "author": "HLV",
    "website": "https://hoanglongvu.com",
    "category": "Inventory/Inventory",
    "license": "LGPL-3",
    "depends": [
        "stock",
        "sale",
        "purchase",
        "mail",
        "misa_fetch_po_button",
    ],
    "data": [
        "security/return_sale_request_security.xml",
        "security/ir.model.access.csv",
        "data/return_sale_request_sequence.xml",
        "views/return_sale_request_views.xml",
        "views/return_sale_request_actions.xml",
        "views/sale_purchase_link_views.xml",
        "wizard/misa_return_sale_sync_wizard_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": True,
}
