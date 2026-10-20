# -*- coding: utf-8 -*-
{
    "name": "HLV Zalo nhóm NCC (đọc tin)",
    "version": "18.0.1.6.0",
    "summary": "Nhận tin nhắn các nhóm Zalo có NCC từ máy nghe bên ngoài, lưu theo nhóm / người gửi, xem cạnh báo giá NCC",
    "description": """
Giai đoạn 1 — CHỈ ĐỌC, chưa có AI:

- Máy nghe (thư mục zalo_listener/ ở gốc repo, chạy ngoài Odoo 24/7) đẩy tin nhóm Zalo về
  /api/zalo-listener/events bằng API key; ảnh / file tải về rồi gửi riêng qua /api/zalo-listener/media.
- Nhóm mới tự hiện trong danh sách nhưng CHƯA ghi tin: thu mua gắn nhóm với NCC rồi bật "Ghi tin".
  Nhóm chưa bật chỉ đếm số tin bỏ qua — không lưu nội dung nhóm không liên quan.
- Thành viên: đánh dấu người của NCC / nhân viên mình (để các giai đoạn sau biết ai hỏi, ai trả lời).
- Báo giá NCC có nút "Tin Zalo" mở tin nhóm của NCC đó từ ngày tạo báo giá.
- Trạng thái máy nghe (đang nối / rớt / mã lỗi / lần cuối báo về) để biết máy nghe còn sống.

Giai đoạn 2 — AI soạn giá (bật trong Cài đặt, mặc định tắt):

- Cron mỗi phút một lần: nhóm có tin mới từ phía NCC → Claude đọc hội thoại + các báo giá đang mở của NCC đó, soạn
  giá / VAT / chiết khấu / tồn kho / hẹn ngày cho từng dòng NCC đã nói tới, kèm trích tin làm căn cứ. NCC chỉ báo
  tồn kho thì lấy giá cũ còn hiệu lực (≤ 7 ngày).
- Sale của phiếu nhận ghi chú + Zalo kèm link /zalo-de-xuat/<id>: xem, sửa, bấm "Ghi vào báo giá" → ghi như NCC tự
  gửi trên trang báo giá (cùng luật: đủ giá + VAT mọi dòng, hoặc hết hàng).
- "AI tự ghi vào báo giá khi chắc chắn" (Cài đặt, mặc định tắt): đề xuất đủ chắc thì ghi thẳng, sale nhận tin "AI đã
  tự ghi" kèm link xem lại; không đủ chắc thì vẫn chờ sale duyệt.

Không đổi hành vi của hlv_vendor_quotation. Không gửi tin nào vào Zalo.
""",
    "author": "HLV",
    "category": "Purchase Management",
    "license": "LGPL-3",
    "depends": [
        "purchase",
        # Menu nằm trong "Báo giá NCC"; nút "Tin Zalo" trên báo giá NCC; cài đặt nằm trong khối Hỏi giá NCC.
        "hlv_vendor_quotation",
        # So API key (utils/api_key.py) — dùng chung, không viết lại.
        "misa_fetch_po_button",
        # AI đọc Zalo: API key + client Claude dùng chung (services/claude_client.py, claude_api_payload.py).
        "hlv_product_agent",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/zalo_message_views.xml",
        "views/zalo_group_views.xml",
        "views/zalo_member_views.xml",
        "views/zalo_listener_views.xml",
        "views/zalo_proposal_views.xml",
        "views/zalo_ai_run_views.xml",
        "views/proposal_templates.xml",
        "views/vendor_quote_views.xml",
        "views/res_config_settings_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
}
