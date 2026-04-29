{
    "name": "AMIS Callback Verified",
    "version": "1.3",
    "category": "Custom",
    "summary": "Nhận callback từ MISA, xác thực chữ ký SHA256 HMAC và xem log trong Odoo",
    "author": "ChatGPT",
    "depends": ["base", "stock", "purchase"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/ir_cron.xml",
        "views/amis_callback_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3"
}
