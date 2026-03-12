# -*- coding: utf-8 -*-
{
    'name': "HLV Smart Report Config",
    'summary': """
        Cấu hình quy tắc in biên bản thông minh dựa trên khách hàng hoặc regex.""",
    'description': """
        Module này cho phép:
        - Cấu hình nhóm khách hàng hoặc regex tên khách hàng để tự động chọn biên bản in.
        - Thiết lập số lượng bản in cho từng loại biên bản.
        - Thêm nút in thông minh trên Stock Picking.
    """,
    'author': "HLV",
    'website': "https://hoanglongvu.com",
    'category': 'Inventory/Inventory',
    'version': '18.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['base', 'stock', 'hlv_a4_report'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/hlv_smart_print_wizard_views.xml',
        'views/hlv_report_rule_views.xml',
        'views/stock_picking_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
