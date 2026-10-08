# -*- coding: utf-8 -*-
"""Nhận diện danh sách hàng sale dán từ Zalo / Excel: tách dòng (models/paste_utils.py) rồi dò
sản phẩm Odoo theo mã. Mỗi dòng: "matched" (chắc chắn), "ambiguous" (nhiều khả năng — sale
chọn), "missing" (không thấy). Đọc theo quyền của sale (không sudo) — như ô tìm sản phẩm.
"""

from odoo.osv import expression

from ..models.paste_utils import parse_paste, pick_best, score_product_match
from .sale_page_payload import product_payload

SEARCH_LIMIT = 20       # ứng viên lấy ra để chấm điểm mỗi dòng
SHOW_CANDIDATES = 5     # ứng viên đưa sale chọn khi chưa chắc


def _candidates(env, row):
    keys = row["codes"] or [row["term"]]
    by_key = expression.OR([
        ["|", "|", ("default_code", "ilike", key), ("barcode", "=", key), ("name", "ilike", key)]
        for key in keys
    ])
    return env["product.product"].search(
        expression.AND([[("purchase_ok", "=", True)], by_key]), limit=SEARCH_LIMIT,
    )


def match_pasted(env, text):
    """Đoạn dán → list {raw, term, qty, unit, qty_found, status, product, candidates}."""
    result = []
    for row in parse_paste(text):
        products = _candidates(env, row)
        scored = [
            (score_product_match(row["codes"], row["words"], p.default_code, p.name), p)
            for p in products
        ]
        best, ranked = pick_best(scored)
        status = "matched" if best else ("ambiguous" if ranked else "missing")
        result.append({
            "raw": row["raw"],
            "term": row["term"],
            "qty": row["qty"],
            "unit": row["unit"],
            "qty_found": row["qty_found"],
            "status": status,
            "product": product_payload(best) if best else None,
            "candidates": [product_payload(p) for p in ranked[:SHOW_CANDIDATES]],
        })
    return result
