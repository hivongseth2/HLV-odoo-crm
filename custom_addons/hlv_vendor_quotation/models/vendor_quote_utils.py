# -*- coding: utf-8 -*-
"""Hàm thuần cho báo giá NCC — không đụng env, không side effect."""

import hashlib
import re
from datetime import timedelta

_CURRENCY_SUFFIX = re.compile(r"(vn)?[dđ]$", re.IGNORECASE)


def parse_vn_number(text):
    """Đọc con số NCC gõ tay theo thói quen Việt Nam.

    Nhận: chuỗi bất kỳ, ví dụ "1.250.000", "1,250,000", "1.250.000,5", "12,5",
    "3 000", "150000đ".
    Trả: float >= 0, hoặc None khi rỗng / không phải số.

    Bẫy: "1.250" và "1,250" đọc là 1250 chứ không phải 1,25 — một dấu duy nhất mà
    đứng trước đúng 3 chữ số được coi là phân cách nghìn, vì giá VND hầu như không
    có phần lẻ 3 chữ số. Có cả chấm lẫn phẩy thì dấu xuất hiện sau cùng là dấu thập
    phân ("1.250.000,5" → 1250000.5).
    """
    s = str(text or "").strip().replace(" ", "").replace(" ", "")
    s = _CURRENCY_SUFFIX.sub("", s)
    if not s or not re.fullmatch(r"[0-9.,]+", s) or not re.search(r"[0-9]", s):
        return None

    separators = set(re.findall(r"[.,]", s))
    if not separators:
        return float(s)

    if len(separators) == 2:
        decimal_sep = s[max(s.rfind("."), s.rfind(","))]
        if s.count(decimal_sep) > 1:
            return None
        thousand_sep = "," if decimal_sep == "." else "."
        integer_part, decimal_part = s.replace(thousand_sep, "").split(decimal_sep)
        return float(f"{integer_part or 0}.{decimal_part or 0}")

    sep = separators.pop()
    parts = s.split(sep)
    if len(parts) > 2:
        if not (1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:])):
            return None
        return float("".join(parts))
    integer_part, tail = parts
    if len(tail) == 3 and integer_part:
        return float(integer_part + tail)
    return float(f"{integer_part or 0}.{tail or 0}")


def format_vn_number(value):
    """Viết số theo kiểu Việt Nam để điền sẵn vào ô nhập.

    Nhận: số (int/float) hoặc None/False.
    Trả: chuỗi chấm phân cách nghìn, phẩy thập phân, tối đa 2 chữ số lẻ, bỏ số 0
    thừa: 1250000 → "1.250.000", 1250.5 → "1.250,5". None/False → "".
    Đọc lại bằng parse_vn_number cho đúng giá trị (đã làm tròn 2 chữ số lẻ).
    """
    if value is None or value is False:
        return ""
    integer_part, decimal_part = f"{value:,.2f}".split(".")
    decimal_part = decimal_part.rstrip("0")
    integer_part = integer_part.replace(",", ".")
    return f"{integer_part},{decimal_part}" if decimal_part else integer_part


def session_fingerprint(token, password):
    """Dấu vân tay của một lần đăng nhập link báo giá.

    Nhận: mã link và mật khẩu hiện tại (chuỗi; None coi như rỗng).
    Trả: chuỗi hex sha256. Đổi mã link hoặc mật khẩu thì dấu vân tay đổi, nên mọi
    phiên đã đăng nhập trước đó tự hết hiệu lực.
    """
    raw = f"{token or ''}\0{password or ''}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def next_failed_count(failed_count, last_failed_at, now, lock_minutes):
    """Số lần sai mật khẩu sau khi ghi nhận thêm một lần sai.

    Nhận: số lần sai đang lưu, thời điểm sai gần nhất (datetime hoặc None), lúc này,
    độ dài cửa sổ khoá (phút).
    Trả: int. Lần sai trước đã cũ hơn cửa sổ khoá thì đếm lại từ 1 — để NCC gõ sai
    vài lần hôm trước không bị khoá ngay ở lần sai đầu tiên hôm sau.
    """
    if not last_failed_at or now - last_failed_at > timedelta(minutes=lock_minutes):
        return 1
    return (failed_count or 0) + 1


def is_login_locked(failed_count, last_failed_at, now, max_attempts, lock_minutes):
    """Link có đang bị khoá đăng nhập không.

    Nhận: số lần sai, thời điểm sai gần nhất (datetime hoặc None), lúc này, số lần
    sai tối đa, độ dài khoá (phút).
    Trả: True khi đã sai đủ max_attempts lần và lần sai cuối chưa quá lock_minutes.
    Chưa từng sai (None) → False.
    """
    if not last_failed_at or (failed_count or 0) < max_attempts:
        return False
    return now - last_failed_at <= timedelta(minutes=lock_minutes)


def best_price_ids(offers):
    """Tìm các báo giá rẻ nhất cho từng mặt hàng.

    Nhận: iterable các bộ (offer_id, group_key, price) — group_key là mặt hàng
    đang so (dòng YCMH), price là đơn giá chưa VAT.
    Trả: set offer_id có giá thấp nhất trong nhóm; hoà giá thì lấy hết. Bỏ qua giá
    None hoặc <= 0 (NCC chưa báo / không cung cấp). Không có gì → set().
    """
    best = {}
    for offer_id, group_key, price in offers:
        if not price or price <= 0:
            continue
        current = best.get(group_key)
        if current is None or price < current[0]:
            best[group_key] = (price, {offer_id})
        elif price == current[0]:
            current[1].add(offer_id)
    return {offer_id for _price, ids in best.values() for offer_id in ids}
