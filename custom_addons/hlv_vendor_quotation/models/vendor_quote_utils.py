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


def paginate(total, page, per_page):
    """Tính phân trang cho danh sách.

    Nhận: tổng số bản ghi, số trang người dùng yêu cầu (int/chuỗi/None, đếm từ 1),
    số bản ghi mỗi trang (> 0).
    Trả: dict {"page", "page_count", "offset", "limit"}. Trang không hợp lệ hoặc
    vượt quá thì kẹp về khoảng [1, page_count]; total = 0 vẫn trả page_count = 1.
    """
    page_count = max(1, -(-int(total) // per_page))
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    page = min(max(page, 1), page_count)
    return {
        "page": page,
        "page_count": page_count,
        "offset": (page - 1) * per_page,
        "limit": per_page,
    }


def match_by_product(items, candidates):
    """Ghép một-một dòng báo giá với dòng YCMH theo sản phẩm, giữ thứ tự.

    Nhận: items là iterable (item_id, product_id) cần ghép; candidates là iterable
    (candidate_id, product_id) còn trống. Cả hai theo thứ tự hiển thị.
    Trả: dict {item_id: candidate_id}. Item không còn candidate cùng sản phẩm thì
    không có trong dict; mỗi candidate dùng tối đa một lần (YCMH có 2 dòng cùng mã
    thì 2 dòng báo giá cùng mã ghép lần lượt vào từng dòng).
    """
    free = {}
    for candidate_id, product_id in candidates:
        free.setdefault(product_id, []).append(candidate_id)
    matched = {}
    for item_id, product_id in items:
        if free.get(product_id):
            matched[item_id] = free[product_id].pop(0)
    return matched


def rank_vendor_suggestions(coverage, order_stats, limit):
    """Xếp hạng NCC nên hỏi giá cho một nhóm sản phẩm.

    Nhận:
    - coverage: iterable (partner_id, product_id, source) — source "po" là NCC đã từng
      bán sản phẩm đó cho mình, "pricelist" là NCC có trong bảng giá NCC của sản phẩm.
    - order_stats: dict partner_id → (số đơn mua đã xác nhận, ngày mua gần nhất hoặc None).
    - limit: số NCC tối đa trả về.
    Trả: list dict {partner_id, product_ids (set), from_pricelist (bool), order_count,
    last_date}, xếp: phủ nhiều mặt hàng hơn → mua nhiều đơn hơn → mua gần đây hơn.
    Không có dữ liệu → [].
    """
    vendors = {}
    for partner_id, product_id, source in coverage:
        vendor = vendors.setdefault(partner_id, {
            "partner_id": partner_id,
            "product_ids": set(),
            "from_pricelist": False,
        })
        vendor["product_ids"].add(product_id)
        if source == "pricelist":
            vendor["from_pricelist"] = True
    for vendor in vendors.values():
        vendor["order_count"], vendor["last_date"] = order_stats.get(vendor["partner_id"], (0, None))

    def sort_key(vendor):
        last = vendor["last_date"]
        return (-len(vendor["product_ids"]), -vendor["order_count"], -(last.toordinal() if last else 0))

    return sorted(vendors.values(), key=sort_key)[:limit]


def build_share_message(company_name, vendor_name, quote_names, item_count, deadline_text, url, password):
    """Tin nhắn sale dán vào Zalo gửi NCC.

    Nhận: tên công ty mình, tên NCC, list số báo giá, tổng số mặt hàng, hạn báo giá đã
    định dạng ("" nếu không có hạn), link, mật khẩu (chuỗi).
    Trả: chuỗi nhiều dòng. Một số báo giá thì nêu số; nhiều số thì gộp "N yêu cầu báo giá".
    """
    if len(quote_names) == 1:
        subject = f"yêu cầu báo giá {quote_names[0]}"
    else:
        subject = f"{len(quote_names)} yêu cầu báo giá ({', '.join(quote_names)})"
    lines = [
        f"Kính gửi {vendor_name},",
        f"{company_name} gửi {subject} — {item_count} mặt hàng.",
    ]
    if deadline_text:
        lines.append(f"Hạn báo giá: {deadline_text}.")
    lines += [
        f"Quý công ty vui lòng điền giá tại: {url}",
        f"Mật khẩu: {password}",
        "Trân trọng cảm ơn!",
    ]
    return "\n".join(lines)


def deadline_hint(deadline, today, urgent_days=2):
    """Nhắc hạn báo giá cho NCC.

    Nhận: ngày hạn (date hoặc None), hôm nay (date), số ngày coi là gấp.
    Trả: (chữ, mức) với mức "over" (đã quá hạn), "urgent" (hôm nay hoặc còn <= urgent_days
    ngày), "ok" (còn xa). Không có hạn → ("", "").
    """
    if not deadline:
        return "", ""
    days = (deadline - today).days
    if days < 0:
        return "Đã quá hạn", "over"
    if days == 0:
        return "Hết hạn hôm nay", "urgent"
    return f"Còn {days} ngày", "urgent" if days <= urgent_days else "ok"
