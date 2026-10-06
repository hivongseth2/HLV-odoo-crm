# -*- coding: utf-8 -*-
{
    "name": "HLV PO Reconcile Report",
    "version": "18.0.1.0.0",
    "summary": "Cron 19h gửi mail + lưu Google Drive file Excel đối chiếu Đơn mua hàng Odoo - MISA",
    "author": "HLV",
    "category": "Purchase Management",
    "depends": [
        "mail",
        # Logic đối chiếu: MisaExtensionController._reconcile_po_only_data
        "misa_purchase_request_sync",
    ],
    "external_dependencies": {"python": ["xlsxwriter"]},
    "data": [
        "data/ir_config_parameter.xml",
        "data/ir_cron.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
