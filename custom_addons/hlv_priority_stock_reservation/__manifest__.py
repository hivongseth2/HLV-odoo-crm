# -*- coding: utf-8 -*-
{
    'name': "HLV Priority Stock Reservation",
    'summary': """
        Hiện danh sách các đơn đang dự trữ để người dùng chọn hủy dự trữ khi thiếu hàng.
    """,
    'description': """
        Module này ghi đè action_assign trên stock.picking để thực hiện logic:
        1. Khi người dùng nhấn 'Kiểm tra tình trạng còn hàng' (Check Availability).
        2. Nếu đơn hàng không đủ hàng để dự trữ.
        3. Hiển thị một bảng danh sách (wizard) các đơn hàng khác đang dự trữ các sản phẩm này.
        4. Người dùng tự chọn hủy dự trữ của các đơn nào để nhường hàng cho đơn hiện tại.
    """,
    'author': "Antigravity",
    'website': "https://www.example.com",
    'category': 'Inventory/Inventory',
    'version': '1.1',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/stock_unreserve_wizard_views.xml',
    ],
    'license': 'LGPL-3',
}
