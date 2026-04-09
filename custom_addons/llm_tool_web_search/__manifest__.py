{
    "name": "LLM Tool Web Search",
    "version": "18.0.1.0.0",
    "category": "Productivity/Tools",
    "author": "HLV",
    "summary": "Cho phép AI tìm kiếm và đọc nội dung từ các trang web được cấu hình",
    "description": """
        Module cung cấp công cụ cho AI assistant để tìm kiếm và trích xuất nội dung
        từ các trang web được cấu hình sẵn (ketnoitieudung.vn, mecsu.vn, visior.vn, ...).

        Tính năng:
        - Tìm kiếm nội dung trên các website qua DuckDuckGo
        - Trích xuất nội dung bài viết từ URL
        - Cấu hình danh sách website được phép truy cập
        - Giới hạn domain để đảm bảo an toàn
    """,
    "depends": ["llm_tool"],
    "data": [
        "security/ir.model.access.csv",
        "views/web_search_site_views.xml",
        "data/llm_tool_data.xml",
    ],
    "external_dependencies": {
        "python": ["requests", "bs4"],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
