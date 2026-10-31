{
    "name": "AMIS Callback — HĐĐT cho đơn POS",
    "version": "1.1",
    "category": "Point of Sale",
    "summary": "Tạo hóa đơn điện tử meInvoice nháp cho mỗi đơn POS đã thanh toán, kế toán duyệt rồi gửi CQT",
    "depends": ["amis_callback", "point_of_sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/amis_callback_config_views.xml",
        "views/meinvoice_invoice_views.xml",
        "views/pos_order_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
