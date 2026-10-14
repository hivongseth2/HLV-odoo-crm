# -*- coding: utf-8 -*-
{
    "name": "HLV Nhập file NCC (Excel + AI ghép mã)",
    "version": "18.0.1.3.0",
    "summary": "Thu mua tải file Excel tồn kho / bảng giá của NCC, Claude duyệt ghép mã NCC với sản phẩm bên mình",
    "description": """
Mỗi NCC gửi một mẫu Excel riêng (tiếng Việt / Anh / Trung, tiêu đề một hoặc hai tầng). Người bên mình
(thu mua) làm hết, NCC không phải vào trang nào:

- Tải file lên (menu Báo giá NCC → Nhập file NCC). Lần đầu của NCC: Odoo đề xuất mẫu (dòng tiêu đề, cột
  nào là mã / tên / ĐVT / tồn từng kho), người dùng xem lại một lần; các file sau đọc theo mẫu đó.
- Mỗi dòng: mã NCC đã xác nhận trước đây thì khớp luôn; chưa có thì dò sản phẩm ứng viên theo mã / tên
  rồi Claude duyệt (cùng hãng, cùng model, cùng thông số) — chạy nền.
- Người dùng xác nhận: nhận hết dòng AI "khớp", xem kỹ dòng "có thể", chọn tay khi cần.
- Áp dụng: nhớ mã NCC → sản phẩm cho lần sau; file tồn thì thay bảng Tồn kho NCC, file giá thì cập nhật
  Bảng giá NCC theo từng mã từ ngày áp dụng (giá cũ giữ để tra; mã không có trong file giữ giá cũ). Dòng
  chưa khớp vẫn giữ theo mã NCC.

Một NCC có thể có mẫu file tồn và mẫu file giá riêng — đọc file chọn mẫu khớp tiêu đề.
""",
    "author": "HLV",
    "category": "Purchase Management",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "purchase",
        # Menu nằm trong "Báo giá NCC"; cài đặt nằm trong khối Hỏi giá NCC.
        "hlv_vendor_quotation",
        # API key + client Claude dùng chung (services/claude_client.py).
        "hlv_product_agent",
    ],
    "external_dependencies": {"python": ["openpyxl"]},
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/ir_cron.xml",
        "views/vendor_import_line_views.xml",
        "views/vendor_import_views.xml",
        "views/vendor_import_profile_views.xml",
        "views/vendor_stock_views.xml",
        "views/vendor_price_views.xml",
        "views/vendor_code_suggestion_views.xml",
        "views/code_suggestion_templates.xml",
        "views/res_config_settings_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
}
