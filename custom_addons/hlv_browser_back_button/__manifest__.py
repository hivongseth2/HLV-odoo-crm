{
    "name": "HLV Browser Back Button",
    "version": "18.0.1.0.0",
    "summary": "Thay đổi hành vi nút back để hoạt động như nút Back của trình duyệt",
    "description": """
        Module này thay đổi hành vi của nút back trong Odoo:
        - Nút back (breadcrumb đầu tiên) sẽ sử dụng history.back() của trình duyệt
        - Đưa người dùng về đúng trang trước đó thay vì về menu ứng dụng
        - Giữ nguyên các bộ lọc và trạng thái tìm kiếm
    """,
    "author": "HLV",
    "website": "https://www.hoanglongvu.com",
    "category": "Tools",
    "license": "LGPL-3",
    "depends": ["web"],
    "assets": {
        "web.assets_backend": [
            "hlv_browser_back_button/static/src/js/browser_back_button.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
