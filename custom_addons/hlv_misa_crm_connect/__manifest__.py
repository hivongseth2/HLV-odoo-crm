# -*- coding: utf-8 -*-
{
    "name": "HLV kết nối MISA CRM (API cho bên ngoài)",
    "version": "18.0.1.0.0",
    "summary": "API riêng của Odoo để hệ thống bên ngoài tra khách, tìm hàng, xem/tạo cơ hội, xem báo giá, đơn hàng trên MISA CRM",
    "description": """
Odoo giữ tài khoản MISA CRM (đăng nhập + token dùng chung của misa_fetch_po_button); bên ngoài
gọi /api/misa-crm/* bằng một API key riêng, không bao giờ cầm token MISA.

- Khách hàng: tìm, xem một khách.
- Hàng hóa: tìm (mọi hàng / chỉ hàng còn tồn), giá gợi ý cho một khách.
- Cơ hội: danh mục giai đoạn + nguồn gốc, tìm, xem hàng, TẠO cơ hội kèm hàng.
- Báo giá, đơn hàng: tìm, xem hàng.

Bật/tắt, cho phép ghi, API key: Cài đặt → Tồn kho → "API MISA CRM cho bên ngoài".
Mặc định TẮT. Danh sách route và body: README.md.
""",
    "author": "HLV",
    "category": "Sales",
    "license": "LGPL-3",
    "depends": [
        # Đăng nhập / token CRM, so API key, hàm đọc cơ hội & báo giá, khung lỗi API — dùng chung.
        "misa_fetch_po_button",
    ],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
}
