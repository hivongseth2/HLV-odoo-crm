# -*- coding: utf-8 -*-
{
    "name": "HLV Báo giá NCC qua link",
    "version": "18.0.1.2.0",
    "summary": "Sale gửi link báo giá có mật khẩu cho nhà cung cấp, thu mua so sánh và chọn",
    "description": """
App "Báo giá NCC":
- Sale vào "Theo nhà cung cấp" (hoặc link /odoo/bao-gia-ncc/<id>), tạo yêu cầu báo giá cho NCC —
  gắn YCMH ngay hoặc nhập hàng tự do rồi gắn YCMH sau (mặt hàng tự ghép theo sản phẩm).
- Từ YCMH cũng gửi được cho nhiều NCC một lần (nút "Hỏi giá NCC").
- Mỗi NCC có một link công khai cố định + mật khẩu, hiện mọi yêu cầu báo giá gửi NCC đó.
- NCC nhập đơn giá chưa VAT, VAT, thời gian giao, ghi chú hoặc báo "không có hàng".
- Thu mua (nhóm Mua hàng) so sánh theo từng mặt hàng (giá rẻ nhất tô xanh), bấm "Chọn" để ghi NCC + giá
  vào dòng YCMH; nút "Tạo RFQ" có sẵn sẽ dùng luôn NCC và giá đó.
""",
    "author": "HLV",
    "category": "Purchase Management",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "sale",
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
    "assets": {
        "web.assets_backend": [
            "hlv_vendor_quotation/static/src/scss/vendor_quote_compare.scss",
        ],
    },
    "installable": True,
    "application": False,
}
