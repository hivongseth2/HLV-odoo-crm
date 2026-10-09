# -*- coding: utf-8 -*-
{
    "name": "HLV Báo giá NCC qua link",
    "version": "18.0.3.35.0",
    "summary": "Sale gửi link báo giá có mật khẩu cho nhà cung cấp, thu mua so sánh và chọn",
    "description": """
- Sale làm việc ở trang riêng /hoi-gia-ncc (cùng kiểu /sale_plan, có link trên navbar /sale_plan):
  danh sách theo NCC, tạo yêu cầu báo giá — từ đơn bán (tạo YCMH chờ phê duyệt ngay tại
  đây — YCMH không còn lập trên MISA; một đơn được có nhiều YCMH), từ YCMH, hoặc nhập hàng tự do rồi gắn YCMH sau (mặt hàng tự ghép theo sản phẩm),
  copy tin nhắn Zalo có link + mật khẩu.
- NCC báo hết hàng (phiếu đang hỏi giá hoặc đã lên YCMH): "Hỏi thêm NCC" trong ngăn phiếu gửi các sản
  phẩm còn thiếu cho NCC khác; chọn giá mới là dòng YCMH (chưa lên đơn mua) tự đổi NCC.
- Menu backend "Báo giá NCC" (trong app Yêu cầu mua hàng) cho thu mua tra cứu.
- Từ YCMH cũng gửi được cho nhiều NCC một lần (nút "Hỏi giá NCC").
- Gợi ý NCC theo lịch sử mua hàng + bảng giá NCC của sản phẩm (không hiện giá mua cho sale).
- Lối tắt trong app Mua hàng → Đơn hàng: "Báo giá NCC", "So sánh báo giá NCC".
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
        # Công tắc mật khẩu NCC nằm trong Cài đặt → Mua hàng.
        "purchase",
        "hlv_contact_refine",
        # Mã sale + link riêng từng sale dùng lại cơ chế /misa_sale_status của module này.
        "misa_invoice_status_report",
        "purchase_request",
        "misa_purchase_request_sync",
        # Hàng có trên MISA CRM mà Odoo chưa có: tìm + tạo sản phẩm (misa.api.utils.import_product_from_crm).
        "misa_fetch_po_button",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/mail_message_subtype.xml",
        "data/ir_cron.xml",
        "data/sale_contact_data.xml",
        "views/vendor_quote_views.xml",
        "views/vendor_inquiry_views.xml",
        "views/vendor_quote_line_views.xml",
        "views/vendor_quote_access_views.xml",
        "views/purchase_request_views.xml",
        "wizard/vendor_quote_wizard_views.xml",
        "views/portal_templates.xml",
        "views/portal_grid_templates.xml",
        "views/portal_quote_quick_templates.xml",
        "views/portal_order_templates.xml",
        "views/sale_page_templates.xml",
        "views/sale_price_lookup_templates.xml",
        "views/menus.xml",
        "views/res_config_settings_views.xml",
        "views/sale_contact_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hlv_vendor_quotation/static/src/scss/vendor_quote_compare.scss",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
