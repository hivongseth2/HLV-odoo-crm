# -*- coding: utf-8 -*-
{
    'name': "Chặn Xác nhận Phiếu Đóng Gói",
    'summary': "Ngăn chặn xác nhận hàng loạt đối với phiếu đóng gói (PACK)",
    'description': """
        Module này thêm logic kiểm tra vào nút Xác nhận trong menu Tác vụ.
        Nếu người dùng chọn Phiếu đóng gói (có mã chứa 'PACK'), hệ thống sẽ báo lỗi.
    """,
    'author': "Gemini AI",
    'category': 'Inventory/Inventory',
    'version': '1.0',
    'depends': ['stock'],
    'data': [
        'views/stock_picking_action.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}