{
    "name": "HLV Stock Trace",
    "version": "18.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Theo dõi tồn kho theo thời gian: toàn công ty / theo kho / theo vị trí",
    "description": """
        Trace lịch sử tồn kho của 1 sản phẩm từ 1 mốc thời gian đến hiện tại:
        - Toàn công ty: tồn đầu kỳ vs hiện tại, luồng nhập/bán/chuyển kho, theo từng kho
        - 1 kho cụ thể: luồng qua lại ranh giới kho + luân chuyển nội bộ giữa các vị trí trong kho
        - 1 vị trí cụ thể: timeline chi tiết từng giao dịch với số dư lũy kế
    """,
    "author": "HLV",
    "depends": ["base", "stock", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/stock_trace_views.xml",
        "views/product_template_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hlv_stock_trace/static/src/components/stock_trace/stock_trace_dashboard.scss",
            "hlv_stock_trace/static/src/components/stock_trace/stock_trace_dashboard.xml",
            "hlv_stock_trace/static/src/components/stock_trace/stock_trace_dashboard.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
