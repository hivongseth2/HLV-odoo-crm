# -*- coding: utf-8 -*-
"""Giá trị sale duyệt trên trang đề xuất → đúng dữ liệu một dòng báo giá NCC cần (như NCC tự gửi trên trang báo giá).

Util thuần: vào số / chuỗi, ra dict. Dùng lại cách tách giá + đọc tồn kho của hlv_vendor_quotation (split_unit_price,
read_availability) — cùng luật với trang NCC, không viết luật thứ hai.
"""

from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import (
    FULL_SUPPLY, parse_vn_number, read_availability, split_unit_price,
)

VAT_CODES = ("0", "5", "8", "10", "kct")


def vat_rate(code):
    """Mã VAT ("8", "kct"…) → % (float). Trống / "kct" → 0."""
    return float(code) if code and code != "kct" else 0.0


def submit_values(asked_qty, form, today, keep):
    """Một dòng báo giá từ ô sale nhập. Trả (dict cho hlv.vendor.quote._vendor_submit, câu lỗi hoặc "").

    asked_qty: SL hỏi; today: date hôm nay (giờ VN); keep: {"vendor_note", "invoice_name"} giữ nguyên của dòng.
    form: {"unavailable": bool, "price": chuỗi giá SAU VAT (trước CK nếu có CK), "vat": mã, "discount": chuỗi %,
    "available": chuỗi SL sẵn (trống = có đủ), "backorder_date": date | None, "delivery_days": chuỗi}.
    Hết hàng: chỉ cần tick. Còn lại phải có giá > 0 và VAT; CK 0 ≤ d < 100.
    """
    base = {"vendor_note": keep.get("vendor_note") or "", "invoice_name": keep.get("invoice_name") or ""}
    if form.get("unavailable"):
        return dict(base, **FULL_SUPPLY, unavailable=True, price_unit=0.0, list_price=0.0, discount=0.0, vat=False,
                    delivery_days=0), ""
    price = parse_vn_number(form.get("price") or "")
    if not price:
        return None, "thiếu giá (hoặc tick Hết hàng)"
    vat = form.get("vat") if form.get("vat") in VAT_CODES else ""
    if not vat:
        return None, "chưa chọn VAT"
    discount = parse_vn_number(form.get("discount") or "") or 0.0
    if discount >= 100:
        return None, "chiết khấu phải nhỏ hơn 100%"
    available = parse_vn_number(form.get("available") or "") if (form.get("available") or "").strip() else None
    supply, error = read_availability(asked_qty, available, form.get("backorder_date"), False, today)
    if error:
        return None, error
    days = (form.get("delivery_days") or "").strip()
    net, list_net = split_unit_price(price, vat_rate(vat), discount if discount else None)
    return dict(base, **supply, unavailable=False, price_unit=net, list_price=list_net, discount=discount, vat=vat,
                delivery_days=int(days) if days.isdigit() else 0), ""
