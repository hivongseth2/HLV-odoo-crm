# -*- coding: utf-8 -*-
"""Gọt kết quả tra cứu trước khi đưa Claude: bỏ trường chỉ dành cho giao diện, cắt danh sách dài.

Mỗi lần Claude đọc kết quả là tính token; một mã bán nhiều có hàng trăm phiếu kho / dòng đơn.

Util thuần: vào dict / list, ra dict / list. Không đụng ``self.env``.
"""
import json

# Trường chỉ phục vụ giao diện trang tra tồn, Claude không cần.
DROPPED_KEYS = frozenset({"image_url", "warehouse_id", "child_product_id", "location_id", "ok"})
MAX_LIST_ITEMS = 30
MAX_RESULT_CHARS = 14000


def compact(data, max_items=MAX_LIST_ITEMS):
    """Bỏ DROPPED_KEYS và giá trị rỗng, cắt list dài hơn max_items.

    Nhận: dict / list / giá trị thường (lồng nhau tuỳ ý).
    Trả: bản mới cùng cấu trúc. List bị cắt có thêm một phần tử cuối dạng
        ``{'_con_lai': n}`` để Claude biết còn sót bao nhiêu.
    Biên: số 0 / False vẫn giữ (là số liệu thật); chỉ bỏ None, "" và list / dict rỗng.
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key in DROPPED_KEYS:
                continue
            value = compact(value, max_items)
            if value is None or value == "" or value == [] or value == {}:
                continue
            result[key] = value
        return result
    if isinstance(data, (list, tuple)):
        items = [compact(item, max_items) for item in data[:max_items]]
        if len(data) > max_items:
            items.append({"_con_lai": len(data) - max_items})
        return items
    if isinstance(data, float):
        return round(data, 2)
    return data


def fit_result(data, max_chars=MAX_RESULT_CHARS):
    """compact() rồi thu dần số mục mỗi list cho tới khi JSON vừa max_chars.

    Trả: dict / list đã gọt. Biên: gọt tới 3 mục / list vẫn quá dài thì trả bản 3 mục đó
    (không cắt giữa chừng một giá trị — JSON hỏng còn tệ hơn dài).
    """
    limit = MAX_LIST_ITEMS
    result = compact(data, limit)
    while limit > 3 and len(json.dumps(result, ensure_ascii=False, default=str)) > max_chars:
        limit = max(3, limit // 2)
        result = compact(data, limit)
    return result


def clamp_int(value, default, low, high):
    """Số nguyên trong [low, high]. Biên: không đọc được số -> default."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, low), high)
