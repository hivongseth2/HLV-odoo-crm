{
    "name": "HLV Product Flow Analysis",
    "version": "18.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Phân tích lưu thông hàng hóa & nhà cung cấp theo tuần/tháng/quý/năm",
    "description": """
        Module phân tích luồng hàng hóa:
        - Xem tần suất xuất/nhập/lưu kho theo sản phẩm
        - Xem nhà cung cấp thường xuyên mua hàng
        - Lọc theo tuần, tháng, quý, năm
        - Gợi ý tồn kho tối thiểu cho từng mặt hàng
    """,
    "author": "HLV",
    "depends": ["base", "stock", "sale_management", "purchase", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/product_flow_dashboard_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/product_flow_dashboard.scss",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/product_flow_dashboard.xml",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/product_flow_dashboard.js",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
