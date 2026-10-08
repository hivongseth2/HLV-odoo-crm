# -*- coding: utf-8 -*-
{
    "name": "HLV Hướng dẫn nội bộ",
    "version": "18.0.1.0.0",
    "summary": "Trang /huong-dan cho sale đọc các hướng dẫn sử dụng (HTML + ảnh) tải lên từ backend",
    "description": """
- Quản lý tải lên một file .html hoặc .zip (index.html + ảnh/CSS) cho mỗi hướng dẫn; bấm Lưu là
  có hiệu lực, không cần nâng cấp module.
- Người dùng nội bộ đọc ở /huong-dan (danh sách theo nhóm) và /huong-dan/<đường-dẫn>/.
- Mỗi hướng dẫn có thể giới hạn cho một số nhóm người dùng.
- Link "Hướng dẫn" trên navbar /sale_plan (nếu có module trang sale).
""",
    "author": "HLV",
    "category": "Productivity",
    "license": "LGPL-3",
    "depends": ["base", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/sale_guide_views.xml",
        "views/guide_page_templates.xml",
    ],
    "installable": True,
    "application": True,
}
