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

App riêng "MISA CRM API", chỉ người có quyền "Quản lý API MISA CRM" thấy:
- Hướng dẫn API: từng endpoint có header, tham số, payload mẫu, response mẫu, lệnh curl điền
  sẵn URL + key để chạy thử.
- Cấu hình: bật/tắt API (mặc định TẮT), cho phép tạo dữ liệu, tạo API key.
""",
    "author": "HLV",
    "category": "Sales",
    "license": "LGPL-3",
    "depends": [
        # Đăng nhập / token CRM, so API key, hàm đọc cơ hội & báo giá, khung lỗi API — dùng chung.
        "misa_fetch_po_button",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/api_doc_templates.xml",
        "views/api_doc_views.xml",
        "views/api_config_views.xml",
        "views/menus.xml",
        "data/api_docs.xml",
    ],
    "installable": True,
    "application": True,
}
