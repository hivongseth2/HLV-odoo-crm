{
    "name": "HLV Stock Origin Audit",
    "version": "18.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Điều tra nguồn gốc tồn kho: hàng đang nằm ở vị trí này từ đâu ra",
    "description": """
        Trả lời câu hỏi "cái này ở đâu chui ra" cho từng lượng tồn cụ thể:
        - Khớp FIFO giữa các lượt nhập và xuất của một vị trí để biết lượng
          đang tồn thuộc về lượt nhập nào.
        - Truy ngược chuỗi nguồn gốc qua các vị trí nội bộ, tới tận nhà cung
          cấp / khách trả / sản xuất / điều chỉnh kiểm kho.
        - Chấm mức nghi ngờ và chỉ ra bất thường: lệch sổ sách, xuất không
          nguồn, hàng đến từ chỉnh tồn, move không phiếu, ghi lùi ngày, tồn
          đọng ở vị trí trung chuyển, tồn âm, giữ chỗ vượt tồn.
        - Quét cả kho để tìm sẵn các trường hợp như vậy.
    """,
    "author": "HLV",
    "depends": ["stock", "web", "hlv_stock_trace"],
    "data": [
        "security/ir.model.access.csv",
        "views/stock_origin_audit_views.xml",
        "views/product_template_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hlv_stock_origin_audit/static/src/origin_audit/origin_audit.scss",
            "hlv_stock_origin_audit/static/src/origin_audit/origin_audit.xml",
            "hlv_stock_origin_audit/static/src/origin_audit/origin_audit.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
