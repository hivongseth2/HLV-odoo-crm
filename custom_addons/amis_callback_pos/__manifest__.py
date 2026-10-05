{
    "name": "AMIS Callback — HĐĐT cho đơn POS",
    "version": "1.0",
    "category": "Point of Sale",
    "summary": "Tự xuất hóa đơn điện tử meInvoice (máy tính tiền) cho mỗi đơn POS đã thanh toán",
    "depends": ["amis_callback", "point_of_sale"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/amis_callback_config_views.xml",
        "views/meinvoice_invoice_views.xml",
        "views/pos_order_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
