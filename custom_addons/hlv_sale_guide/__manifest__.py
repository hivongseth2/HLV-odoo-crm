# -*- coding: utf-8 -*-
{
    "name": "HLV Hướng dẫn nội bộ",
    "version": "18.0.1.3.0",
    "summary": "Trang /huong-dan cho sale đọc hướng dẫn sử dụng (HTML + ảnh, PDF) xếp theo cây thư mục",
    "description": """
- Quản lý tải lên một file .html, .pdf hoặc .zip (index.html + ảnh/CSS) cho mỗi hướng dẫn; bấm Lưu
  là có hiệu lực, không cần nâng cấp module. Nút "+ Thêm hướng dẫn" ngay trên trang /huong-dan.
- Hướng dẫn xếp trong cây thư mục lồng nhau. /huong-dan: cây bên trái, khung xem bên phải
  (điện thoại: chỉ cây, bấm là mở trang); /huong-dan/<đường-dẫn>/ mở toàn trang.
- Mỗi hướng dẫn có thể giới hạn cho một số nhóm người dùng.
- Mỗi hướng dẫn kèm tuỳ chọn một bản Markdown (tải file .md hoặc gõ thẳng) để sau này làm
  kiến thức cho AI; sale không thấy phần này.
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
