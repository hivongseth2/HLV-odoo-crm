# -*- coding: utf-8 -*-
{
    'name': 'HLV POS Loyalty Portal Integration',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Tích điểm bán hàng tại quầy POS trực tiếp vào Tài khoản Portal',
    'description': """
        Tích hợp hệ thống Loyalty Hoàng Long Vũ với Odoo 18 POS:
        - Quét mã vạch Barcode/QR từ App Mobile của khách hàng tại quầy POS.
        - Gắn điểm trực tiếp vào Tài khoản Portal (hlv.loyalty.portal.account).
        - Tự động tạo tài khoản Portal cho SĐT mới chưa từng đăng ký (Phương án A).
        - Ghi nhận chi tiết mã đơn hàng POS và lý do tích điểm vào lịch sử.
    """,
    'author': 'HLV',
    'depends': [
        'point_of_sale',
        'hlv_loyalty',
    ],
    'data': [
        'views/pos_order_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'hlv_pos_loyalty/static/src/css/pos_loyalty.css',
            'hlv_pos_loyalty/static/src/xml/loyalty_button.xml',
            'hlv_pos_loyalty/static/src/js/loyalty_button.js',
            'hlv_pos_loyalty/static/src/js/loyalty_order_patch.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
