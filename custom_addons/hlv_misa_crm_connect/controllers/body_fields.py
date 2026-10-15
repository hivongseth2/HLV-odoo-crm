# -*- coding: utf-8 -*-
"""Đọc và kiểm từng trường trong body của các route /api/misa-crm/* — sai thì ApiError 400.

Quy ước cho route SỬA: trường không có trong body (hoặc null) = giữ nguyên trên MISA.
"""
from datetime import date

from odoo.addons.misa_fetch_po_button.controllers.misa_product_api import ApiError, _number, _text

from ..services.crm_payloads import page_size
from .api_common import int_field

MAX_LINES = 200
# Trường đầu báo giá: tên trong body -> kiểu ("number" >= 0 / "text" / "date").
QUOTE_HEADER_FIELDS = {
    "quote_date": "date", "expired_date": "date", "description": "text", "payment_terms": "text",
    "validity_days": "text", "delivery_days": "text",
    "prepaid": "number", "shipping_cost": "number", "commission_percent": "number",
}
QUOTE_REQUIRED_ON_CREATE = ("shipping_cost", "commission_percent")


def keyword(data, required=False):
    return _text(data, "keyword", required=required)


def paging(data):
    """(page ≥ 1, limit 1..100) trong body."""
    page = max(1, int_field(data, "page", required=False, default=1))
    return page, page_size(int_field(data, "limit", required=False, default=10))


def has(data, key):
    """Body có gửi trường ``key`` (khác null) không."""
    return data.get(key) is not None


def date_field(data, key, required=False):
    """Ngày "YYYY-MM-DD" trong body; không có -> None (hoặc 400 nếu ``required``)."""
    value = _text(data, key, required=required)
    if not value:
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ApiError(400, "invalid_field", "'%s' phải dạng YYYY-MM-DD." % key)
    return value


def text_or_number(data, key):
    """Ô chữ của MISA mà bên gọi hay gửi số (vd số ngày hiệu lực): nhận cả hai, trả chuỗi."""
    value = data.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return ("%g" % value)
    return _text(data, key, required=False) or None


def non_negative(data, key):
    value = _number(data, key)
    if value < 0:
        raise ApiError(400, "invalid_field", "'%s' không được âm." % key)
    return value


def lines(data, allow_empty=True):
    """Dòng hàng trong body, đã kiểm kiểu. Không gửi 'lines' -> None (route sửa: giữ hàng cũ).

    Mỗi dòng: ``code``, ``qty`` > 0, đúng MỘT trong ``price_after_tax`` / ``price`` (≥ 0), tuỳ
    chọn ``description``, ``customer_item`` (báo giá: tên hàng theo cách khách gọi).
    """
    if not has(data, "lines"):
        return None
    items = data["lines"]
    if not isinstance(items, list) or len(items) > MAX_LINES:
        raise ApiError(400, "invalid_field", "'lines' phải là danh sách (tối đa %s dòng)." % MAX_LINES)
    if not items and not allow_empty:
        raise ApiError(400, "invalid_field", "'lines' phải có ít nhất một dòng hàng.")
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            raise ApiError(400, "invalid_field", "Mỗi phần tử 'lines' phải là object.")
        code = _text(item, "code")
        qty = _number(item, "qty")
        if qty <= 0:
            raise ApiError(400, "invalid_field", "Số lượng của mã %s phải > 0." % code)
        has_after, has_before = has(item, "price_after_tax"), has(item, "price")
        if has_after == has_before:
            raise ApiError(400, "invalid_field",
                           "Mã %s: gửi đúng MỘT trong 'price_after_tax' (ưu tiên) hoặc 'price'." % code)
        price_key = "price_after_tax" if has_after else "price"
        price = _number(item, price_key)
        if price < 0:
            raise ApiError(400, "invalid_field", "Giá của mã %s không được âm." % code)
        cleaned.append({
            "code": code, "qty": qty, price_key: price,
            "description": _text(item, "description", required=False) or None,
            "customer_item": _text(item, "customer_item", required=False) or None,
        })
    return cleaned


def quote_header(data, create):
    """Trường đầu báo giá có trong body -> dict (khoá như QUOTE_HEADER_FIELDS).

    ``create``: bắt buộc shipping_cost và commission_percent (form MISA bắt buộc hai ô này).
    Sửa: chỉ trả các trường có gửi — trường vắng mặt giữ nguyên trên MISA.
    """
    if create:
        for key in QUOTE_REQUIRED_ON_CREATE:
            if not has(data, key):
                raise ApiError(400, "missing_field", "Thiếu trường '%s' (MISA bắt buộc)." % key)
    header = {}
    for key, kind in QUOTE_HEADER_FIELDS.items():
        if not has(data, key):
            continue
        if kind == "date":
            header[key] = date_field(data, key)
        elif kind == "number":
            header[key] = non_negative(data, key)
        elif key in ("validity_days", "delivery_days"):
            header[key] = text_or_number(data, key)
        else:
            header[key] = _text(data, key, required=False) or None
    return header
