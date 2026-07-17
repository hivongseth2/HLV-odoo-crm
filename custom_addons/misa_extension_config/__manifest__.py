# -*- coding: utf-8 -*-
{
    "name": "MISA Extension Config",
    "version": "18.0.1.0.0",
    "summary": "Cấu hình động nút/element cho MISA Browser Extension",
    "description": """
Module master config cho Chrome Extension MISA→Odoo.

Extension fetch config qua API GET /api/extension/config, render UI element
theo config (button, badge, status_field, grid_column, skeleton...).

Mọi thay đổi UI (tên nút, vị trí, màu, bật/tắt) không cần update extension.
Có config_version để extension cũ không chạy sai.
    """,
    "author": "HLV",
    "category": "Configuration",
    "depends": [
        "misa_purchase_request_sync",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/misa_extension_config_views.xml",
        "data/seed_elements.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": True,
}