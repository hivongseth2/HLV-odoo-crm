# -*- coding: utf-8 -*-
{
    "name": "HLV Báo giá NCC qua link",
    "version": "18.0.1.0.0",
    "summary": "Gửi link báo giá có mật khẩu cho nhà cung cấp, so sánh giá theo YCMH",
    "description": """
Từ một Yêu cầu mua hàng, gửi yêu cầu báo giá cho nhiều nhà cung cấp:
- Mỗi NCC có một link công khai cố định + mật khẩu, hiện mọi yêu cầu báo giá gửi NCC đó.
- NCC nhập đơn giá chưa VAT, VAT, thời gian giao, ghi chú hoặc báo "không có hàng".
- Thu mua so sánh theo từng mặt hàng (giá rẻ nhất tô xanh), bấm "Chọn" để ghi NCC + giá
  vào dòng YCMH; nút "Tạo RFQ" có sẵn sẽ dùng luôn NCC và giá đó.
""",
    "author": "HLV",
    "category": "Purchase Management",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "purchase_request",
        "misa_purchase_request_sync",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "views/vendor_quote_views.xml",
        "views/vendor_quote_line_views.xml",
        "views/vendor_quote_access_views.xml",
        "views/purchase_request_views.xml",
        "wizard/vendor_quote_wizard_views.xml",
        "views/portal_templates.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
}
