# -*- coding: utf-8 -*-
{
    'name': "Shopee Order Fetch",
    'summary': "Lấy thông tin đơn hàng Shopee bị sót qua API get_order_detail",
    'description': """
        Module cho phép nhập mã đơn hàng Shopee (order_sn) và gọi API Shopee
        để lấy thông tin chi tiết đơn hàng. Dùng để tạo lại các đơn bị bỏ sót
        trong quá trình đồng bộ tự động.
    """,
    'author': "HLV",
    'website': "https://www.hlv.vn",
    'category': 'Sales',
    'version': '18.0.1.2.0',
    'depends': ['sale', 'stock', 'sale_shopee'],
    'data': [
        'security/ir.model.access.csv',
        'views/shopee_order_fetch_wizard_views.xml',
        'views/sale_order_views.xml',
        'views/stock_picking_views.xml',
    ],
    # 'installable': True,  # TẠM TẮT THEO YÊU CẦU
    'installable': False,
    'application': False,
    'license': 'LGPL-3',
}
