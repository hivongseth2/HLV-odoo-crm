# -*- coding: utf-8 -*-
{
    'name': "Shopee Product Management",
    'summary': "Quản lý sản phẩm Shopee từ Odoo — sync, xem và đẩy sản phẩm lên Shopee",
    'description': """
        Module quản lý sản phẩm Shopee tích hợp trực tiếp vào ứng dụng Shopee trong Odoo.

        Tính năng Phase 1:
        - Đồng bộ danh sách sản phẩm từ Shopee về Odoo (get_item_list + get_item_base_info)
        - Xem thông tin chi tiết: tên, SKU, giá, tồn kho, trạng thái
        - Lọc sản phẩm theo trạng thái, cửa hàng, thời gian
        - Liên kết sản phẩm Shopee với product.product trong Odoo

        Service layer đã implement sẵn (Phase 2):
        - get_category, get_attribute_tree, get_brand_list
        - add_item, update_item, delete_item
    """,
    'author': "HLV",
    'website': "https://www.hlv.vn",
    'category': 'Sales',
    'version': '18.0.1.2.0',
    'depends': [
        'mail',
        'sale',
        'shopee_order_fetch',   # auth, signing, shopee.shop / shopee.account models
        'shopee_webhook',       # menu_shopee_root (ứng dụng Shopee)
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/shopee_product_views.xml',
        'views/shopee_product_sync_wizard_views.xml',
        'views/shopee_push_stock_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
