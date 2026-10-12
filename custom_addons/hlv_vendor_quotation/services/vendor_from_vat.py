# -*- coding: utf-8 -*-
"""Tạo nhanh NCC từ mã số thuế trên trang /hoi-gia-ncc: sale gõ MST mà danh bạ chưa có NCC đó.

Dùng lại tra cứu VietQR của hlv_contact_refine (nút "Lấy thông tin MST" trên form liên hệ) — chuẩn hoá MST,
tìm liên hệ trùng MST, gọi VietQR — không viết lại.

NCC tạo với supplier_rank = 1: vừa để trang hỏi giá coi là NCC (vendor_quote_access._vendor_partner_domain),
vừa để amis_callback tự xếp việc đẩy NCC sang MISA (res_partner_sync._misa_should_sync_vendor): đợi mirror
MISA ~2 phút xem MISA đã có NCC trùng MST chưa — có thì gắn account_object_id sẵn có, chưa có thì tạo bên
MISA rồi ghi account_object_id về liên hệ. Ở đây không gọi MISA trực tiếp.
"""

from odoo.exceptions import UserError


def _existing(env, tax_code):
    return env["res.partner"].sudo()._hlv_vietqr_find_existing_partner(tax_code)


def _vendor_payload(partner):
    return {"id": partner.id, "name": partner.display_name, "vat": partner.vat or ""}


def _check_usable(partner):
    """Liên hệ trùng MST chỉ dùng làm NCC được khi là công ty gốc đang hoạt động — chọn người liên hệ /
    hồ sơ lưu trữ là ra link báo giá thứ hai cho cùng một công ty."""
    if not partner.active:
        raise UserError('MST này thuộc liên hệ đã lưu trữ "%s". Nhờ thu mua mở lại liên hệ đó.' % partner.display_name)
    if partner.parent_id or not partner.is_company:
        raise UserError('MST này đang gắn trên "%s" (không phải công ty gốc). Nhờ thu mua sửa liên hệ đó.'
                        % partner.display_name)


def lookup(env, vat):
    """Tra MST. Trả ``{"vat", "existing": {...}|None, "business": {...}|None}``.

    existing: liên hệ đã có MST này (kèm ``is_vendor``); business: thông tin VietQR khi danh bạ chưa có.
    Lỗi (UserError): MST sai dạng, VietQR không trả lời / không thấy doanh nghiệp.
    """
    Partner = env["res.partner"].sudo()
    tax_code = Partner._hlv_vietqr_normalize_tax_code(vat)
    partner = _existing(env, tax_code)
    if partner:
        is_vendor = bool(partner.filtered_domain(env["hlv.vendor.quote.access"]._vendor_partner_domain()))
        return {"vat": tax_code, "business": None,
                "existing": dict(_vendor_payload(partner), is_vendor=is_vendor, active=partner.active,
                                 root_company=not partner.parent_id and partner.is_company)}
    data = Partner._hlv_vietqr_fetch_business(tax_code)["data"]
    return {"vat": tax_code, "existing": None, "business": {
        "name": str(data.get("name") or "").strip(),
        "street": str(data.get("address") or "").strip(),
        "status": str(data.get("status") or "").strip(),
    }}


def create(env, vat):
    """Tạo (hoặc dùng lại) NCC theo MST. Trả ``{"partner": {id, name, vat}, "created": bool}``.

    Đã có công ty gốc trùng MST → dùng lại; chưa là NCC thì đánh dấu NCC (supplier_rank = 1, cũng đẩy sang
    MISA như NCC mới). Chưa có → lấy tên / địa chỉ từ VietQR NGAY LÚC TẠO (không tin dữ liệu trình duyệt gửi).
    """
    Partner = env["res.partner"].sudo()
    tax_code = Partner._hlv_vietqr_normalize_tax_code(vat)
    partner = _existing(env, tax_code)
    if partner:
        _check_usable(partner)
        if not partner.supplier_rank:
            partner.supplier_rank = 1
        return {"partner": _vendor_payload(partner), "created": False}
    business = Partner.hlv_vietqr_lookup_business(tax_code)
    partner = Partner.create({
        "name": business["name"],
        "vat": business["vat"],
        "street": business["street"] or False,
        "country_id": business["country_id"] or False,
        "company_type": "company",
        "is_company": True,
        "supplier_rank": 1,
    })
    partner.message_post(body="Tạo nhanh từ MST trên trang Hỏi giá NCC (thông tin VietQR%s)." % (
        ", tình trạng: " + business["status"] if business["status"] else ""))
    return {"partner": _vendor_payload(partner), "created": True}
