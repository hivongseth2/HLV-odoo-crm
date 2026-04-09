{
    "name": "LLM Tool File Export",
    "version": "18.0.1.0.0",
    "category": "Productivity/Tools",
    "author": "HLV",
    "summary": "Cho phép AI tạo và xuất file xlsx/csv cho người dùng tải về",
    "description": """
        Module cung cấp công cụ cho AI assistant để tạo file có cấu trúc
        (xlsx, csv) từ dữ liệu và đính kèm vào cuộc trò chuyện.

        Tính năng:
        - Tạo file Excel (.xlsx) với định dạng chuyên nghiệp
        - Tạo file CSV
        - Tự động đính kèm file vào tin nhắn trong cuộc trò chuyện
        - Hỗ trợ chuyển đổi kiểu dữ liệu (số, văn bản)
    """,
    "depends": ["llm_tool"],
    "data": [
        "data/llm_tool_data.xml",
    ],
    "external_dependencies": {
        "python": ["openpyxl"],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
