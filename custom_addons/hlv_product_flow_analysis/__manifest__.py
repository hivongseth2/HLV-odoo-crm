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
            # SCSS partials
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/dashboard_base.scss",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/dashboard_tables.scss",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/dashboard_modal.scss",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/dashboard_responsive.scss",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar.scss",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar_charts.scss",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar_charts_ext.scss",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar_correlation.scss",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar_trend.scss",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar_help.scss",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar_ai.scss",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/drilldown.scss",
            # XML templates
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/product_flow_dashboard.xml",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar_products.xml",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar_suppliers.xml",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar_analysis.xml",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar_correlation.xml",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar_trend.xml",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar_help.xml",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/sidebar_ai.xml",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/content_products.xml",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/content_suppliers.xml",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/content_planning.xml",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/drilldown_panel.xml",
            # JS modules
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/dashboard_data.js",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/chart_products.js",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/chart_suppliers.js",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/chart_correlation.js",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/chart_trend.js",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/chart_analysis.js",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/drilldown.js",
            "hlv_product_flow_analysis/static/src/components/product_flow_dashboard/product_flow_dashboard.js",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
