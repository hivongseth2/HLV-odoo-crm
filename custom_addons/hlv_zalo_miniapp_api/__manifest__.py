# -*- coding: utf-8 -*-
{
    "name": "HLV - Zalo Mini App API",
    "version": "18.0.1.0.2",
    "category": "Sales",
    "author": "HLV",
    "summary": "REST API endpoints for Zalo Mini App integration",
    "description": """
        Module cung cấp REST API cho Zalo Mini App.
        - Danh mục sản phẩm (pos.category)
        - Sản phẩm (product.product variant)
        - Contact / Khách hàng (res.partner + hlv.loyalty.portal.account)
        - Giỏ hàng (sale.order draft)
        - Đơn hàng (sale.order)
    """,
    "depends": [
        "sale_management",
        "stock",
        "contacts",
        "hlv_loyalty",
        "point_of_sale",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/product_template_views.xml",
        "views/product_product_views.xml",
        "views/res_partner_views.xml",
        "views/banner_views.xml",
        "views/sale_order_views.xml",
        "views/pos_category_views.xml",
        "views/res_config_settings_views.xml",
        "views/zalo_loyalty_portal_account_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}