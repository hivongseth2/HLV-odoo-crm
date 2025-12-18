# -*- coding: utf-8 -*-
{
    'name': "HLV Priority Stock Reservation",
    'summary': """
        Tự động hủy dự trữ các đơn hàng có hạn giao xa để ưu tiên cho đơn hàng đang kiểm tra.
    """,
    'description': """
        Module này ghi đè action_assign trên stock.picking để thực hiện logic:
        1. Khi người dùng nhấn 'Kiểm tra tình trạng còn hàng' (Check Availability).
        2. Nếu đơn hàng không đủ hàng để dự trữ.
        3. Hệ thống tìm các đơn hàng khác đang giữ hàng nhưng có ngày giao (x_studio_hn_giao_hng) xa hơn đơn hiện tại.
        4. Tự động hủy dự trữ của các đơn đó để nhường hàng cho đơn hiện tại.
    """,
    'author': "Antigravity",
    'website': "https://www.example.com",
    'category': 'Inventory/Inventory',
    'version': '1.0',
    'depends': ['stock'],
    'data': [],
    'license': 'LGPL-3',
}
