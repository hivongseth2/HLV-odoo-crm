# -*- coding: utf-8 -*-
{
    "name": "MISA Purchase Request Sync",
    "version": "18.0.1.4.1",
    "summary": "API endpoints + button to sync Purchase Request from MISA CRM Browser Extension",
    "description": """
Module cung cấp:
- 2 endpoints RESTful cho Browser Extension (Chrome MV3) đẩy YCMH từ MISA CRM về Odoo:
    + GET  /api/extension/pr/check?name=<name> : Kiểm tra YCMH đã tồn tại trên Odoo hay chưa.
    + POST /api/extension/pr/create : Tạo YCMH mới từ payload JSON của CRM.
- Xác thực bằng token lưu trong System Parameter (misa_extension_token).
- Nút "Đẩy sang MISA CRM" trên form Purchase Request (stub - TODO).
""",
    "author": "HLV",
    "category": "Purchase Management",
    "depends": [
        "purchase_request",
        "purchase_stock",
        "mail",
        "sale",
        "misa_fetch_po_button",
        "hlv_contact_refine",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter.xml",
        "data/ir_cron.xml",
        "views/purchase_request_view.xml",
        "views/purchase_order_view.xml",
        "views/wizard_views.xml",
        "views/price_history_wizard_views.xml",
        "views/misa_sync_queue_views.xml",
        "views/res_partner_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "misa_purchase_request_sync/static/src/components/proposed_fields.js",
            "misa_purchase_request_sync/static/src/components/proposed_fields.xml",
            "misa_purchase_request_sync/static/src/css/rfq_dialog.css",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
