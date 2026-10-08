# -*- coding: utf-8 -*-
"""Hàm thuần đọc danh sách hàng sale dán từ Zalo / Excel — không đụng env, không side effect.

Mẫu sale hay gõ (mỗi dòng một mặt hàng):
    Vòng bi 6212-ZZCM NSK: 2 cái
    Máy phay gỗ cầm tay Makita 3709    1    cái
    2608595053:       6
    SPAX2800                      (không ghi số lượng → 1, đánh dấu để sale kiểm)
Dòng nhắn kèm ("@Vân Anh báo giúp e", "em xin giá ạ") không có chữ số hoặc có "@" → bỏ.
"""

import re

MAX_LINES = 100
MAX_QTY = 100000
# Đơn vị hay gặp sau số lượng — chỉ để nhận ra "2 cái" là số lượng, không dùng làm ĐVT.
UNITS = {
    "cái", "c", "chiếc", "bộ", "sợi", "s", "cuộn", "hộp", "thùng", "m", "mét", "kg", "cây", "đôi",
    "tấm", "bao", "lít", "viên", "con", "pcs", "pc", "set", "cặp", "gói", "tuýp", "lọ", "chai",
}
# Số lượng ở cuối dòng: "…: 2 cái", "… x 2", "…   6", "…\t6". Dấu nhân "x" phải có khoảng trắng
# đứng trước — "SPAX2800" là một mã, không phải "SPA × 2800".
_QTY_TAIL = re.compile(
    r"(?P<sep>\s*[:=]\s*|\s+[x×*]\s*|\s{2,}|\t+|\s)(?P<qty>\d+(?:[.,]\d+)?)\s*(?P<unit>[^\W\d_]{1,6})?\s*[.;,]?\s*$",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[^\s,;:()]+")


def _qty_value(text):
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def parse_paste_line(raw):
    """Một dòng dán → {raw, term, codes, words, qty, unit, qty_found}; dòng không phải mặt hàng → None.

    term: phần mô tả hàng (bỏ số lượng); codes: các "mã" trong term (có chữ số, dài ≥ 3 —
    "6212-ZZCM", "HR30218JP5", "2608595053", "3709"); words: chữ còn lại để chấm điểm (hãng,
    loại hàng). Không đọc được số lượng → qty = 1, qty_found = False.
    """
    line = (raw or "").strip().strip("-•*·").strip()
    if not line or "@" in line or not any(ch.isdigit() for ch in line):
        return None
    qty, unit, term = 1.0, "", line
    match = _QTY_TAIL.search(line)
    if match:
        value = _qty_value(match.group("qty"))
        unit_word = (match.group("unit") or "").lower()
        separated = match.group("sep").strip() != "" or len(match.group("sep")) >= 2 or "\t" in match.group("sep")
        # Số cuối dòng chỉ là số lượng khi có dấu ngăn (":", "x", nhiều khoảng trắng / tab) hoặc
        # có đơn vị — "Máy phay Makita 3709" thì 3709 là mã, không phải 3709 cái.
        if value and 0 < value <= MAX_QTY and (separated or unit_word in UNITS) and \
                (not match.group("unit") or unit_word in UNITS):
            qty, unit = value, unit_word
            term = line[:match.start()].strip(" :=x×*-\t")
    if not term:
        return None
    tokens = [t.strip(".-/") for t in _TOKEN.findall(term)]
    codes = [t for t in tokens if len(t) >= 3 and any(ch.isdigit() for ch in t)]
    words = [t for t in tokens if t and t not in codes and len(t) >= 2]
    return {
        "raw": raw.strip(), "term": term, "codes": codes, "words": words,
        "qty": qty, "unit": unit, "qty_found": bool(match) and term != line,
    }


def parse_paste(text):
    """Đoạn dán → list dòng đã đọc (bỏ dòng nhắn kèm), tối đa MAX_LINES. Rỗng → []."""
    rows = []
    for raw in (text or "").splitlines():
        row = parse_paste_line(raw)
        if row:
            rows.append(row)
        if len(rows) >= MAX_LINES:
            break
    return rows


def score_product_match(codes, words, default_code, name):
    """Điểm khớp một sản phẩm với một dòng dán (càng cao càng khớp; 0 = không khớp mã nào).

    Mã trùng hẳn mã nội bộ: +10; mã nằm trong mã nội bộ: +5; mã nằm trong tên: +3. Mỗi chữ
    còn lại (hãng NSK, Makita…) có trong mã / tên: +1 — để tách 6212-ZZCM NSK khỏi 6212-ZZCM SKF.
    """
    code_text = (default_code or "").lower()
    name_text = (name or "").lower()
    score = 0
    for code in (c.lower() for c in codes):
        if code == code_text:
            score += 10
        elif code in code_text:
            score += 5
        elif code in name_text:
            score += 3
    if codes and not score:
        return 0
    haystack = code_text + " " + name_text
    score += sum(1 for word in words if word.lower() in haystack)
    return score


def pick_best(scored):
    """[(điểm, x)] → (x tốt nhất hoặc None, các x xếp hạng). Chọn được khi chỉ một ứng viên
    có điểm, hoặc điểm cao nhất hơn hẳn hạng nhì; hoà điểm → None để sale chọn."""
    ranked = [item for score, item in sorted(scored, key=lambda pair: -pair[0]) if score > 0]
    scores = sorted((score for score, _item in scored if score > 0), reverse=True)
    if not ranked:
        return None, []
    if len(scores) == 1 or scores[0] > scores[1]:
        return ranked[0], ranked
    return None, ranked
