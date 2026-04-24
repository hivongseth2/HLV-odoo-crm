{
    "name": "AMIS Callback Verified",
    "version": "1.1",
    "category": "Custom",
    "summary": "Nhận callback từ MISA, xác thực chữ ký SHA256 HMAC và xem log trong Odoo",
    "author": "ChatGPT",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/amis_callback_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3"
}
