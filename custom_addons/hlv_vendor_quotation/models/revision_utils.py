# -*- coding: utf-8 -*-
"""Hàm thuần cho đề xuất thay đổi đơn mua của NCC (phiên bản / snapshot) — không đụng env."""

from .vendor_quote_utils import DATE_FMT, format_vn_number

# Sai số so SL / giá: chênh dưới mức này coi như không đổi.
EPSILON = 1e-6


def line_changes(old_qty, new_qty, old_price, new_price, old_day, new_day):
    """Những gì NCC đổi trên một dòng đơn mua.

    *_qty: số lượng; *_price: đơn giá SAU VAT; *_day: ngày giao (date). new_* = None nghĩa là NCC không
    sửa ô đó. Trả dict chỉ gồm khoá thật sự đổi: {"qty": (cũ, mới), "price": (cũ, mới), "day": (cũ, mới)};
    không đổi gì → {}. Giá so theo 2 chữ số lẻ (như ô hiện cho NCC): giá sau VAT tính lại từ giá chưa VAT lệch
    vài phần nghìn (30.000,0024) không phải NCC đổi giá.
    """
    changes = {}
    if new_qty is not None and abs(new_qty - (old_qty or 0.0)) > EPSILON:
        changes["qty"] = (old_qty, new_qty)
    if new_price is not None and round(new_price, 2) != round(old_price or 0.0, 2):
        changes["price"] = (old_price, new_price)
    if new_day is not None and new_day != old_day:
        changes["day"] = (old_day, new_day)
    return changes


def line_change_error(new_qty, received_qty, new_price, new_day, today):
    """Kiểm giá trị NCC đề xuất cho một dòng. Trả câu lỗi (không có tên hàng — nơi gọi thêm) hoặc "".

    SL: không âm (0 = hết hàng) và không dưới SL kho đã nhận; giá: > 0; ngày giao: không trước hôm nay.
    Giá trị None (không sửa) không kiểm.
    """
    if new_qty is not None:
        if new_qty < 0:
            return "số lượng không được âm (hết hàng thì để 0)"
        if new_qty < (received_qty or 0.0) - EPSILON:
            return f"kho đã nhận {format_vn_number(received_qty)} — không giảm dưới số đó"
    if new_price is not None and new_price <= 0:
        return "đơn giá phải lớn hơn 0"
    if new_day is not None and new_day < today:
        return "ngày giao không được trước hôm nay"
    return ""


def change_text(name, changes, uom=""):
    """Một dòng mô tả thay đổi: "Pin 18V: SL 2 → 0 Cái; giá 40.000 → 45.000 (sau VAT); giao 30/10/2026 → 05/11/2026"."""
    parts = []
    if "qty" in changes:
        old, new = changes["qty"]
        parts.append(f"SL {format_vn_number(old)} → {format_vn_number(new)}{(' ' + uom) if uom else ''}")
    if "price" in changes:
        old, new = changes["price"]
        parts.append(f"giá {format_vn_number(round(old))} → {format_vn_number(round(new))} (sau VAT)")
    if "day" in changes:
        old, new = changes["day"]
        parts.append(f"giao {old.strftime(DATE_FMT) if old else '—'} → {new.strftime(DATE_FMT)}")
    return f"{name}: " + "; ".join(parts)


def is_dates_only(changes_list):
    """Mọi dòng chỉ đổi ngày giao (không đổi SL / giá)."""
    return bool(changes_list) and not any(("qty" in c or "price" in c) for c in changes_list)


def needs_approval(changes_list, state, approval_states, confirmed):
    """Đề xuất của NCC có phải chờ thu mua duyệt (tạo phiên bản) không.

    changes_list: các dict line_changes của mọi dòng đổi; state: trạng thái đơn mua; approval_states: trạng thái
    cấu hình "tạo phiên bản chờ duyệt"; confirmed: đơn đã xác nhận. Đơn đã xác nhận mà chỉ đổi ngày giao → không
    cần duyệt (tự cập nhật, có ghi lại). Còn lại: cần duyệt khi đơn ở trạng thái trong approval_states, không thì áp ngay.
    """
    if confirmed and is_dates_only(changes_list):
        return False
    return state in approval_states
