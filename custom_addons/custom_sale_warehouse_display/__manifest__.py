# -*- coding: utf-8 -*-
{
    'name': "Sale Order Multi-Warehouse Display",
    'summary': "Hiển thị các kho hàng thực tế thực hiện đơn hàng trên List View",
    'description': """
        Thêm cột 'Kho hàng thực tế' vào danh sách đơn bán hàng.
        Dữ liệu được lấy từ địa điểm nguồn của các phiếu kho (Pickings).
    """,
    'author': "Your Name",
    'website': "https://yourwebsite.com",
    'category': 'Sales',
    'version': '18.0.1.0.0',
    'depends': ['sale', 'stock', 'sale_stock'],
    'data': [
        'views/sale_order_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}