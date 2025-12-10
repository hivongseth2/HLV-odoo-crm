{
    "name": "HLV Stock Picking Column Filters",
    "version": "18.0.1.0.0",
    "summary": "Add column filters to Stock Picking list view",
    "description": """
        Thêm icon filter vào header các cột trong danh sách lệnh vận chuyển (stock.picking).
        Cho phép lọc nhanh theo: Tham chiếu, Địa điểm, Ngày, Liên hệ, Chứng từ gốc, Batch, Trạng thái.
    """,
    "author": "HLV",
    "website": "https://hoanglongvu.com",
    "license": "LGPL-3",
    "category": "Inventory",
    "depends": ["stock", "web"],
    "data": [
        "security/ir.model.access.csv",
    ],
    "assets": {
        "web.assets_backend": [
            "hlv_stock_picking_filter/static/src/js/stock_picking_filter.js",
            "hlv_stock_picking_filter/static/src/scss/stock_picking_filter.scss",
        ]
    },
    "installable": True,
    "application": False,
}
