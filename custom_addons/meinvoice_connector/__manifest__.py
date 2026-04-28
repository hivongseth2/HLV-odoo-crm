# -*- coding: utf-8 -*-
{
    'name': 'MEinvoice Connector (MISA)',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'Kết nối Odoo 18 với hệ thống hóa đơn điện tử MISA MEinvoice',
    'description': """
MEinvoice Connector
===================
Tích hợp Odoo 18 với hệ thống hóa đơn điện tử MISA MEinvoice (meinvoice.vn).

Tính năng:
- Phát hành hóa đơn điện tử từ hóa đơn bán hàng Odoo
- Tra cứu / kiểm tra trạng thái hóa đơn
- Hủy / điều chỉnh hóa đơn điện tử
- Tải XML / PDF hóa đơn và lưu vào chứng từ Odoo
- Hỗ trợ cả môi trường Sandbox và Production
- Tự động refresh token JWT
    """,
    'author': 'Your Company',
    'website': 'https://yourcompany.vn',
    'license': 'LGPL-3',
    'depends': ['account', 'base_setup'],
    'data': [
        'security/ir.model.access.csv',
        'data/meinvoice_data.xml',
        'views/res_config_settings_views.xml',
        'views/account_move_views.xml',
        'views/meinvoice_log_views.xml',
        'wizard/meinvoice_cancel_wizard_views.xml',
        'wizard/meinvoice_adjust_wizard_views.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'auto_install': False,
    'application': False,
}
