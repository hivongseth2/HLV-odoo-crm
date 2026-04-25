# -*- coding: utf-8 -*-
{
    'name': 'MISA AMIS CRM – Webhook Receiver',
    'version': '18.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Nhận webhook từ MISA AMIS CRM, đồng bộ Khách hàng & Đơn hàng vào Odoo 18',
    'description': """
MISA AMIS CRM Webhook Receiver
===============================
Module nhận sự kiện webhook từ MISA AMIS CRM (crmconnect.misa.vn) và đồng bộ dữ liệu
vào Odoo 18.

Tính năng:
──────────
• Endpoint nhận webhook POST:  /misa/crm/webhook
• Xác thực bằng AppID + Secret (header hoặc query param)
• Xử lý sự kiện: khách hàng (tạo mới / cập nhật), đơn hàng (tạo mới / cập nhật)
• Tự động tạo / cập nhật res.partner từ dữ liệu khách hàng CRM
• Tự động tạo sale.order (nếu module sale đã cài) từ đơn hàng CRM
• Ghi log đầy đủ: raw payload, event type, trạng thái xử lý, lỗi
• Giao diện quản lý log trong Odoo (lọc / tìm kiếm / xem chi tiết)
• Retry thủ công cho log lỗi
• Cấu hình AppID & Secret qua Settings
    """,
    'author': 'Your Company',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['base', 'contacts', 'sale_management'],
    'data': [
        'security/ir.model.access.csv',
        'data/misa_crm_data.xml',
        'views/res_config_settings_views.xml',
        'views/misa_crm_webhook_log_views.xml',
        'views/misa_crm_menus.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
