# -*- coding: utf-8 -*-
{
    'name': "Stock Dashboard Grouped (MISA Integrated)",
    'summary': "Giao diện kho gộp, tích hợp thống kê đơn MISA và phân quyền xem kho",
    'description': """
        - Gom nhóm các thẻ hoạt động vào trong từng Kho.
        - Giao diện Clean UI, nút to, rõ ràng.
        - Thống kê đơn hàng Sale theo ngày MISA (x_studio_misa_order_date).
        - Phân quyền User được xem kho nào.
    """,
    'author': "Your Name",
    'category': 'Inventory/Inventory',
    'version': '18.0.1.0.0',
    'depends': ['base', 'stock', 'sale', 'sale_stock'], # Cần sale_stock để có delivery_status
    'data': [
        'security/security.xml',
        'views/res_users_views.xml',
        'views/stock_warehouse_views.xml',
        'views/sale_order_views.xml'
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}