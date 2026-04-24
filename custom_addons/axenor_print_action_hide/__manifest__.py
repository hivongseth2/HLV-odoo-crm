# -*- coding: utf-8 -*-
{
    "name": "AxenorSuite: Ẩn/Hiện tác vụ In",
    "summary": "Kiểm soát hiển thị tác vụ in báo cáo QWeb theo Người dùng, Công ty hoặc Loại hoạt động.",
    "description": """
AxenorSuite: Ẩn/Hiện tác vụ In
==============================

Module cho phép kiểm soát linh hoạt các báo cáo trong menu In của Odoo.

Tính năng chính:
----------------
- **Ẩn hoặc hiện báo cáo** theo Người dùng, Công ty hoặc Loại hoạt động phiếu kho.
- Áp dụng cho **mọi ir.actions.report** (ví dụ: Đơn bán, Phiếu giao, Hóa đơn...).
- Cấu hình dễ dàng tại backend, dành cho nhóm quản trị.
- Giúp người dùng chỉ thấy các mẫu in phù hợp vai trò và công ty.
- Tăng bảo mật và giảm rối trong danh sách menu "In".

Trường hợp sử dụng:
-------------------
- Ẩn báo cáo nhạy cảm với người dùng không thuộc phòng ban liên quan.
- Giới hạn báo cáo theo từng công ty trong môi trường đa công ty.
- Ẩn mẫu in theo loại hoạt động phiếu kho (Lấy hàng, Đóng gói, Giao hàng...).

Thông tin kỹ thuật:
-------------------
- Mở rộng cấu hình quyền hiển thị cho `ir.actions.report`.
- Tích hợp với cơ chế bảo mật và phân quyền của Odoo.
- Tương thích Odoo CE/EE v18.0.

""",
    "version": "18.0.0.1.0",
    "license": "LGPL-3",
    "author": "AxenorSuite Consultancy Services LLP",
    "website": "https://axenorsuite.com",
    "category": "Administration/Reporting",
    "depends": ["base", "stock"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/report_access_right_view.xml"
        
    ],
    "assets": {
        "web.assets_backend": [
            "axenor_print_action_hide/static/src/js/action_manager_patch.js",
        ]
    },
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": False,
    "auto_install": False,
}
