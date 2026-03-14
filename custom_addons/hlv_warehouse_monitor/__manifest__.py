{
    "name": "HLV Warehouse Monitor",
    "summary": "Giám sát tổng hợp hoạt động kho: nhập, xuất, lấy, gói, chuyển, kiểm",
    "description": """
        Module giám sát trung tâm cho tất cả hoạt động kho hàng.
        
        Phase 1 - Monitor & Hooks:
        - Theo dõi real-time mọi thay đổi: Bán hàng, Mua hàng, Kho
        - Hook vào sale.order, purchase.order, stock.picking
        - Dashboard tùy chỉnh OWL với giao diện riêng
        - Đề xuất hành động khi có thay đổi (PO nhập → gợi ý PICK cho SO)
        - Giám sát theo từng kho
        
        Phase 2 (Planned) - AI Integration:
        - AI phân tích sự kiện và đưa ra quyết định
        - Tự động hóa luồng xử lý
    """,
    "author": "Hoang Long Vu",
    "website": "https://www.hoanglongvu.com",
    "category": "Inventory/Inventory",
    "version": "18.0.1.0.0",
    "license": "OPL-1",
    "depends": [
        "base",
        "stock",
        "sale_management",
        "purchase",
        "web",
    ],
    "data": [
        "security/warehouse_monitor_security.xml",
        "security/ir.model.access.csv",
        "views/warehouse_monitor_event_views.xml",
        "views/warehouse_monitor_config_views.xml",
        "views/warehouse_monitor_dashboard_views.xml",
        "views/warehouse_monitor_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            # Monitor Dashboard
            "hlv_warehouse_monitor/static/src/components/monitor_dashboard/monitor_dashboard.scss",
            "hlv_warehouse_monitor/static/src/components/monitor_dashboard/monitor_dashboard_kpi.xml",
            "hlv_warehouse_monitor/static/src/components/monitor_dashboard/monitor_dashboard_timeline.xml",
            "hlv_warehouse_monitor/static/src/components/monitor_dashboard/monitor_dashboard_suggestions.xml",
            "hlv_warehouse_monitor/static/src/components/monitor_dashboard/monitor_dashboard.xml",
            "hlv_warehouse_monitor/static/src/components/monitor_dashboard/monitor_dashboard.js",
            # Queue Screen (PICK/PACK hospital display)
            "hlv_warehouse_monitor/static/src/components/queue_screen/queue_screen.scss",
            "hlv_warehouse_monitor/static/src/components/queue_screen/queue_screen.xml",
            "hlv_warehouse_monitor/static/src/components/queue_screen/queue_screen.js",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
