# -*- coding: utf-8 -*-
{
    "name": "HLV Chứng từ chi NCC (UNC) + tab Tài chính trang NCC",
    "version": "18.0.1.5.0",
    "summary": "Kế toán tải UNC / chứng từ chi lên đề nghị chi MISA; NCC xem số đã chi + chứng từ trên link báo giá",
    "description": """
- Trang /unc-ncc riêng cho kế toán (nhóm quyền "Kế toán: chứng từ chi NCC"): tìm đề nghị chi (amis.payment.request)
  của đơn mua, mở ra xem đủ thông tin, tải ảnh / PDF / Word lên (UNC, phiếu chi…), ẩn / xoá chứng từ.
- Trang NCC (link báo giá): tab "Tài chính" cạnh "Đơn mua hàng" — số đã chi, đang xử lý, còn lại; danh sách đề nghị
  chi kèm chứng từ kế toán gửi, lọc theo số / đơn mua / trạng thái / có chứng từ / ngày.
- Chi tiết đơn mua của NCC: khung "Thanh toán" — đã thanh toán / thanh toán một phần / chưa, các đề nghị chi liên quan.

Đề nghị chi coi là "đã chi" theo đúng quy tắc của amis_callback (PAYMENT_PAID_STATES). Không đổi luồng MISA.
""",
    "author": "HLV",
    "category": "Purchase Management",
    "license": "LGPL-3",
    "depends": [
        # Trang NCC (link báo giá): khung trang, đăng nhập, tab, chi tiết đơn mua.
        "hlv_vendor_quotation",
        # Đề nghị chi MISA (amis.payment.request) + quy tắc "đã chi".
        "amis_callback",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/accountant_templates.xml",
        "views/vendor_finance_templates.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
}
