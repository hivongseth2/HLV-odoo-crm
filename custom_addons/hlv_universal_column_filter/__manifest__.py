{
    "name": "HLV Universal Column Filters",
    "version": "18.0.1.0.0",
    "summary": "Add column filters to any list view (Purchase, Stock, Sales)",
    "description": """
        Thêm icon filter vào header các cột trong danh sách.
        Tự động áp dụng cho: purchase.order, stock.picking, sale.order.
        Không cần cấu hình - tự động detect tất cả cột.
    """,
    "author": "HLV",
    "website": "https://hoanglongvu.com",
    "license": "LGPL-3",
    "category": "Tools",
    "depends": ["web", "stock", "purchase", "sale"],
    "assets": {
        "web.assets_backend": [
            "hlv_universal_column_filter/static/src/js/universal_column_filter.js",
            "hlv_universal_column_filter/static/src/scss/universal_column_filter.scss",
        ]
    },
    "installable": True,
    "application": False,
}
