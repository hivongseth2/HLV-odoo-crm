# -*- coding: utf-8 -*-
"""Gọt kết quả tra cứu trước khi đưa Claude: bỏ trường chỉ dành cho giao diện, cắt danh sách dài.

Mỗi lần Claude đọc kết quả là tính token; một mã bán nhiều có hàng trăm phiếu kho / dòng đơn.

Util thuần: vào dict / list, ra dict / list. Không đụng ``self.env``.
"""
import json
import re
import unicodedata

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


# Từ quá chung, khớp nhau không nói lên hai món giống nhau.
_GENERIC_WORDS = frozenset({
    "cai", "bo", "cay", "chiec", "hop", "loai", "may", "hang", "va", "cho", "co", "dung", "x", "mm", "cm",
})


def _plain(text):
    """Chữ thường, bỏ dấu tiếng Việt (đ -> d) để so từ."""
    text = (text or "").lower().replace("đ", "d")
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


def has_all_words(words, text):
    """Văn bản có chứa đủ mọi từ khoá không, bỏ qua dấu / khoảng trắng / gạch nối.

    Nhận: words (tập từ, thường từ name_tokens), text (tên / mã / mô tả). Trả: bool.
    So trên chuỗi đã bỏ mọi ký tự không phải chữ / số: tên hàng trong Odoo viết dính / tách không
    thống nhất ("bulong" / "bu lông", "18V-350" / "18v350"), so nguyên từ là trượt mất hàng.
    Biên: words rỗng -> True.
    """
    compact = re.sub(r"[^a-z0-9]", "", _plain(text))
    return all(re.sub(r"[^a-z0-9]", "", _plain(word)) in compact for word in words)


def name_tokens(text):
    """Tập từ đặc trưng của một tên hàng để so độ giống.

    Nhận: tên / mô tả. Trả: frozenset từ (chữ thường, không dấu) dài >= 2, bỏ từ chung chung.
    Giữ nguyên cụm có số (M18, FPD3, 6204) — đó thường là thứ phân biệt dòng hàng.
    Biên: rỗng / None -> frozenset().
    """
    words = re.findall(r"[a-z0-9]+(?:[-.][a-z0-9]+)*", _plain(text))
    return frozenset(word for word in words if len(word) >= 2 and word not in _GENERIC_WORDS)


# Cụm từ khoá ngắn hơn ngần này ký tự ("HD", "HM") khớp gần như mọi tên hàng.
MIN_KEYWORD_CHARS = 3
# Bậc khớp, nhỏ là sát: tên bắt đầu bằng cả cụm / tên bắt đầu bằng đúng loại hàng và có đủ từ /
# tên chứa cụm / tên có đủ từ / chỉ khớp mã hoặc mô tả.
TIER_NAME_STARTS, TIER_NAME_TYPE, TIER_NAME_PHRASE, TIER_NAME_WORDS, TIER_OTHER = 0, 1, 2, 3, 4


def squash_text(text):
    """Chữ để so: thường, bỏ dấu (đ -> d), bỏ mọi ký tự không phải chữ / số. Biên: None -> ''."""
    return re.sub(r"[^a-z0-9]", "", _plain(text))


def _leading_type(text):
    """Phần đầu cụm từ khoá tới hết từ đặc trưng đầu tiên: "may khoan milwaukee" -> "maykhoan",
    "pin milwaukee 18v" -> "pin". Tên hàng trong kho mở đầu bằng loại hàng ("Máy khoan ...", "Pin ...")."""
    words = re.findall(r"[a-z0-9]+", _plain(text))
    for index, word in enumerate(words):
        if word not in _GENERIC_WORDS:
            return "".join(words[:index + 1])
    return ""


def usable_keywords(variants):
    """Các cụm từ khoá đủ dài để lọc, giữ thứ tự, bỏ trùng.

    Nhận: list chuỗi (tu_khoa + tu_khoa_khac). Trả: list chuỗi.
    Biên: phần tử không phải chuỗi / rỗng / ngắn hơn MIN_KEYWORD_CHARS (sau khi bỏ dấu, khoảng
    trắng) -> bỏ.
    """
    seen, result = set(), []
    for text in variants or []:
        key = squash_text(text) if isinstance(text, str) else ""
        if len(key) >= MIN_KEYWORD_CHARS and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def keyword_rank(keywords, name, other_text=""):
    """Một món hàng khớp từ khoá tới đâu, để xếp hạng.

    Trả ``(bậc, -số từ của cụm khớp)``: cùng bậc thì món khớp cụm cụ thể hơn ("máy khoan búa
    makita") đứng trước món chỉ khớp cụm chung ("máy khoan makita") — không thì máy khoan búa chưa
    bán cái nào bị máy vặn vít bán chạy đẩy khỏi danh sách. None nếu không khớp cụm nào.
    So NGUYÊN CỤM với tên (giữ cả chữ "máy": "máy đục" khác "đục" trong "keo trắng đục"), rồi tên mở
    đầu bằng đúng loại hàng, rồi từng từ, rồi mã / mô tả (xem TIER_*).
    Nhận: keywords (list cụm, đã qua usable_keywords), name (tên hàng), other_text (mã + mô tả).
    Biên: keywords rỗng -> (TIER_OTHER, 0).
    """
    if not keywords:
        return (TIER_OTHER, 0)
    best = None
    for text in keywords:
        tier = _phrase_tier(text, name, other_text)
        if tier is not None:
            rank = (tier, -len(name_tokens(text)))
            best = rank if best is None else min(best, rank)
    return best


def _phrase_tier(text, name, other_text):
    """Bậc khớp của MỘT cụm từ khoá với một món; None nếu không khớp."""
    name_key = squash_text(name)
    phrase = squash_text(text)
    words = name_tokens(text)
    leading = _leading_type(text)
    if name_key.startswith(phrase):
        return TIER_NAME_STARTS
    if leading and name_key.startswith(leading) and has_all_words(words, name):
        return TIER_NAME_TYPE
    if phrase in name_key:
        return TIER_NAME_PHRASE
    if words and has_all_words(words, name):
        return TIER_NAME_WORDS
    if has_all_words(words, "%s %s" % (name, other_text)):
        return TIER_OTHER
    return None
