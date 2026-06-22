# -*- coding: utf-8 -*-
{
    "name": "MISA Purchase Request Sync",
    "version": "18.0.1.0.0",
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
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter.xml",
        "views/purchase_request_view.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}