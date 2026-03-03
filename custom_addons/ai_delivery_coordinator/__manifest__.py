# -*- coding: utf-8 -*-
{
    'name': "AI Delivery Coordinator",
    'summary': "Automated Delivery Coordination using GPT",
    'description': """
        Điều phối giao hàng hàng ngày sử dụng GPT:
        - Phân tích đơn hàng (List A, B, C)
        - Phân tuyến: Nhơn Trạch, Long Thành, Mỹ Xuân - Phú Mỹ
        - Phân công phương tiện.
    """,
    'author': "Your Company",
    'category': 'Sales/Delivery',
    'version': '18.0.1.0.0',
    'depends': ['base', 'sale_management', 'stock', 'delivery', 'stock_picking_batch'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/delivery_schedule_views.xml',
        'views/delivery_status_report_views.xml',
        'views/delivery_report_views.xml',
        'wizard/delivery_coordinator_wizard_views.xml',
        'wizard/delivery_schedule_create_wizard_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
}
