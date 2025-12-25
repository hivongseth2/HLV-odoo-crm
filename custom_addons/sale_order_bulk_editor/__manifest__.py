# -*- coding: utf-8 -*-
{
    'name': "Sale Order Bulk Editor",
    'summary': "Cho phép chỉnh sửa nhanh đơn hàng trực tiếp trên list view",
    'description': """
        Thêm khả năng chỉnh sửa nhanh (inline edit) các trường của đơn hàng
        ngay trên giao diện danh sách hiện tại.
        
        Features:
        - Editable list view (inline editing)
        - Multi-edit support (sửa nhiều đơn cùng lúc)
        - Nút "Chi tiết" để mở form view đầy đủ
    """,
    'author': "Antigravity",
    'website': "http://www.yourcompany.com",
    'category': 'Sales',
    'version': '1.0',
    'depends': ['sale', 'sale_management'],
    'data': [
        'views/sale_order_bulk_view.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
