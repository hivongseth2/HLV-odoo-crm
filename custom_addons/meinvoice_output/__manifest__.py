# -*- coding: utf-8 -*-
{
    'name': 'MEinvoice – Hóa đơn đầu ra (Đầu vào hệ thống)',
    'version': '18.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Lấy hóa đơn điện tử đầu ra từ MISA meInvoice, hạch toán và đánh dấu Sale Order đã xuất hóa đơn',
    'description': """
MEinvoice Output Invoice Manager (Odoo 18)
==========================================
Quản lý hóa đơn điện tử đầu ra lấy về từ MISA meInvoice (Inbot API).

Tính năng:
──────────
• Kết nối MISA meInvoice Inbot API (BaseURL2) – lấy SecureToken → JWT
• Lấy danh sách hóa đơn đầu ra (getinvoices) về bảng riêng trong Odoo
• Hiển thị danh sách hóa đơn dạng list với các trường chính
• Đánh dấu Hạch toán 1 hoặc nhiều hóa đơn cùng lúc (gọi API MISA)
• Liên kết hóa đơn meInvoice ↔ Sale Order Odoo (theo số hóa đơn / mã ref)
• Tự động đánh dấu Sale Order "Đã xuất hóa đơn MISA" sau khi hạch toán
• Lịch sử API call (log)
• Cấu hình credentials trong Settings
    """,
    'author': 'Your Company',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['base', 'sale_management', 'base_setup', 'amis_callback'],
    'data': [
        'security/ir.model.access.csv',
        'data/meinvoice_output_data.xml',
        'views/res_config_settings_views.xml',
        'views/meinvoice_output_invoice_views.xml',
        'views/sale_order_views.xml',
        'views/meinvoice_output_menus.xml',
        'wizard/meinvoice_fetch_wizard_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
