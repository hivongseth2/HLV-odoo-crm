# -*- coding: utf-8 -*-
"""Xếp kết quả tìm hàng cho Claude: hàng lẻ khớp mã lên đầu, combo / hàng ngưng xuống cuối.

MISA tìm theo "chứa" và xếp theo ngày sửa: một mã model hay bán (FPD3) khớp cả trăm combo
có chứa nó, hàng lẻ đúng mã bị đẩy khỏi trang đầu — Claude chỉ thấy combo và kết luận
"chưa có hàng lẻ", tạo trùng. Nên lấy nhiều rồi tự xếp lại, và nói rõ còn bao nhiêu kết quả.

Util thuần: vào list dict, ra list / dict. Không đụng ``self.env``.
"""
import re

_CODE_NOISE = re.compile(r"[\s\-_./]+")


def normalize_code(value):
    """Mã để so: in hoa, bỏ khoảng trắng / - _ . /. Biên: None -> ''."""
    return _CODE_NOISE.sub("", (value or "").upper())


def product_kind(product):
    """'ngung' (đã ngưng), 'combo', hoặc 'le' (hàng lẻ) — theo cờ MISA và quy ước tên / mã."""
    name = (product.get("name") or "").strip().casefold()
    code = (product.get("code") or "").strip().upper()
    if name.startswith("[ngưng") or name.startswith("[ngung") or product.get("active") is False:
        return "ngung"
    if product.get("is_combo") or code.startswith("CB-") or name.startswith("combo"):
        return "combo"
    return "le"


def _rank(product, query_code):
    kind = product_kind(product)
    code = normalize_code(product.get("code"))
    if query_code and code == query_code:
        return 0
    if kind == "le" and query_code and query_code in code:
        return 1
    return {"le": 2, "combo": 3, "ngung": 4}[kind]


def rank_products(products, code="", name=""):
    """Sắp lại kết quả: trùng đúng mã > hàng lẻ chứa mã > hàng lẻ khác > combo > hàng ngưng.

    Nhận: list dict kết quả MISA (code, name, is_combo, active...), mã / tên đã tìm.
    Trả: list mới, mỗi dict thêm khoá 'kind'. Giữ thứ tự MISA giữa các mục cùng hạng.
    Biên: không có mã tìm -> chỉ xếp theo loại hàng.
    """
    query_code = normalize_code(code or name)
    ranked = sorted(enumerate(products or []), key=lambda item: (_rank(item[1], query_code), item[0]))
    return [dict(product, kind=product_kind(product)) for _index, product in ranked]


def summarize_search(products, code="", name="", shown=12, fetched_limit=None):
    """Kết quả gửi Claude: tối đa `shown` mục đã xếp + đếm theo loại + cảnh báo còn sót.

    Nhận: kết quả MISA, mã / tên đã tìm, số mục hiển thị, số mục đã xin MISA (để biết
    MISA còn kết quả chưa trả).
    Trả dict ``{'data', 'total_fetched', 'counts', 'truncated'}``; truncated True khi
    MISA trả đủ fetched_limit mục (có thể còn nữa) hoặc phải cắt bớt khi hiển thị.
    """
    ranked = rank_products(products, code, name)
    counts = {"le": 0, "combo": 0, "ngung": 0}
    for product in ranked:
        counts[product["kind"]] += 1
    more_on_misa = bool(fetched_limit) and len(ranked) >= fetched_limit
    return {
        "data": ranked[:shown],
        "total_fetched": len(ranked),
        "counts": counts,
        "truncated": more_on_misa or len(ranked) > shown,
    }
