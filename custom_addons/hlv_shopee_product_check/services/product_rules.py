# -*- coding: utf-8 -*-
"""Đọc dữ liệu sản phẩm Shopee và các lỗi liên kết thấy được không cần AI — util thuần.

Vào dict / chuỗi, ra dict / chuỗi. Không đụng env, không gọi mạng.

Một "phân loại" (unit) là đơn vị Odoo liên kết được: sản phẩm Shopee không có phân loại thì là chính
sản phẩm đó (model_id = 0), có phân loại thì là từng model. shopee.item của Odoo lưu đúng cặp
(item_id, model_id) này.

Không có quy tắc so tên / SKU ở đây: tên hai bên viết khác nhau là bình thường, SKU Shopee hay gõ sai.
Có cùng một hàng hay không là việc của AI (match_payload.py), dựa trên thành phần thật trong hộp.
"""

import re

# Trạng thái Shopee coi như sản phẩm đã mất (get_item_base_info.item_status).
DELETED_STATUSES = ("SELLER_DELETE", "SHOPEE_DELETE")
# Mô tả Shopee thường ~2000 chữ (thông số, ưu điểm, bảo hành, hashtag); thành phần nằm ở đầu nếu có.
DESCRIPTION_MAX = 1500
HASHTAG = re.compile(r"#\S+")

ISSUE_OK = "ok"
ISSUE_MISSING = "missing"
ISSUE_MODEL_GONE = "model_gone"
ISSUE_PLACEHOLDER = "placeholder"
ISSUE_DUPLICATE = "duplicate"
ISSUES = [
    (ISSUE_OK, "Không"),
    (ISSUE_MISSING, "Không còn trên Shopee"),
    (ISSUE_MODEL_GONE, "Phân loại không còn"),
    (ISSUE_PLACEHOLDER, "Gắn SP tạm \"Shopee Sales\""),
    (ISSUE_DUPLICATE, "Một phân loại gắn nhiều SP"),
]
# Lỗi mà AI không xét được: một bên không có hàng để so.
ISSUES_WITHOUT_PAIR = (ISSUE_MISSING, ISSUE_MODEL_GONE, ISSUE_PLACEHOLDER)
# Liên kết trỏ hàng / phân loại đã xoá trên Shopee: không còn đơn nào về qua nó, nhưng đồng bộ tồn vẫn gửi
# model_id chết lên Shopee. Không phải map nhầm — tách riêng để danh sách map nhầm không bị ngập
# (dữ liệu thật: ~30% liên kết của shop MILWAUKEE).
ISSUES_STALE = (ISSUE_MISSING, ISSUE_MODEL_GONE)

VERDICT_MATCH = "match"
VERDICT_PROBABLE = "probable"
VERDICT_MISMATCH = "mismatch"
VERDICTS = [
    (VERDICT_MATCH, "Cùng hàng"),
    (VERDICT_PROBABLE, "Chưa chắc"),
    (VERDICT_MISMATCH, "Khác hàng"),
]

RESULT_PENDING = "pending"
RESULT_OK = "ok"
RESULT_REVIEW = "review"
RESULT_MISMATCH = "mismatch"
RESULT_STALE = "stale"
RESULT_FIXED = "fixed"
RESULTS = [
    (RESULT_PENDING, "Đang kiểm"),
    (RESULT_OK, "Đúng"),
    (RESULT_REVIEW, "Cần xem"),
    (RESULT_MISMATCH, "Map nhầm"),
    (RESULT_STALE, "Liên kết cũ"),
    (RESULT_FIXED, "Đã sửa"),
]


def model_key(value):
    """Khoá model để so khớp: Shopee và Odoo ghi "không có phân loại" là 0, "0", rỗng hoặc False.

    Nhận: int / chuỗi / None / False. Trả: chuỗi id model, hoặc "" khi không có phân loại.
    """
    text = str(value or "").strip()
    return "" if text in ("", "0") else text


def variation_name(tier_variation, tier_index):
    """Tên phân loại ghép từ các tầng, vd "Đỏ / 40ml".

    Nhận: ``tier_variation`` của get_model_list (list ``{"name", "option_list": [{"option"}]}``),
    ``tier_index`` của model (list int). Trả: chuỗi; chỉ số lệch / thiếu thì bỏ tầng đó; không có gì → "".
    """
    names = []
    for level, index in enumerate(tier_index or []):
        if level >= len(tier_variation or []):
            break
        options = tier_variation[level].get("option_list") or []
        if 0 <= index < len(options):
            option = (options[index].get("option") or "").strip()
            if option:
                names.append(option)
    return " / ".join(names)


def item_description(item):
    """Mô tả sản phẩm Shopee dạng chữ, rút gọn.

    Nhận: một phần tử ``item_list`` của get_item_base_info. Shopee để mô tả thường ở ``description``,
    mô tả mở rộng ở ``description_info.extended_description.field_list`` (lấy các khối ``text``).
    Trả: chuỗi đã bỏ hashtag (#milwaukee_chinh_hang... chỉ là nhiễu), gộp khoảng trắng, tối đa
    DESCRIPTION_MAX ký tự; không có mô tả → "".
    """
    text = item.get("description") or ""
    if not text:
        fields = ((item.get("description_info") or {}).get("extended_description") or {}).get("field_list") or []
        text = "\n".join(field.get("text") or "" for field in fields if field.get("field_type") == "text")
    text = HASHTAG.sub("", text)
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()
    return text[:DESCRIPTION_MAX]


def price_and_stock(data):
    """Giá bán hiện tại và tồn khả dụng từ một item (không phân loại) hoặc một model của Shopee.

    Nhận: dict có thể có ``price_info`` (list ``{"current_price"}``) và ``stock_info_v2``
    (``{"summary_info": {"total_available_stock"}}``). Trả: (float, int); thiếu khoá → (0.0, 0).
    """
    prices = data.get("price_info") or []
    price = float(prices[0].get("current_price") or 0.0) if prices else 0.0
    summary = (data.get("stock_info_v2") or {}).get("summary_info") or {}
    return price, int(summary.get("total_available_stock") or 0)


def shopee_units(item, models_response=None):
    """Các phân loại của một sản phẩm Shopee, mỗi cái là một đơn vị liên kết được với Odoo.

    Nhận: ``item`` — một phần tử ``item_list`` của get_item_base_info; ``models_response`` — phần
    ``response`` của get_model_list (chỉ cần khi ``item["has_model"]``).
    Trả: list dict ``{"item_id", "model_id", "name", "model_name", "sku", "status", "description",
    "price", "stock"}`` (id là chuỗi, model_id = "0" khi không phân loại — đúng cách sale_shopee
    lưu). Sản phẩm có phân loại mà không có models_response → [] (bên gọi coi như chưa lấy được).
    """
    base = {
        "item_id": str(item.get("item_id")),
        "name": (item.get("item_name") or "").strip(),
        "status": item.get("item_status") or "",
        "description": item_description(item),
    }
    if not item.get("has_model"):
        price, stock = price_and_stock(item)
        return [dict(base, model_id="0", model_name="", sku=(item.get("item_sku") or "").strip(),
                     price=price, stock=stock)]
    if not models_response:
        return []
    tiers = models_response.get("tier_variation") or []
    units = []
    for model in models_response.get("model") or []:
        price, stock = price_and_stock(model)
        # model_name chỉ có ở bản API mới; không có thì ghép từ tier_index.
        name = (model.get("model_name") or "").strip() or variation_name(tiers, model.get("tier_index"))
        sku = (model.get("model_sku") or "").strip() or (item.get("item_sku") or "").strip()
        units.append(dict(base, model_id=str(model.get("model_id")), model_name=name, sku=sku,
                          price=price, stock=stock))
    return units


def detect_issue(fetched, status, model_found, is_placeholder, is_duplicate):
    """Lỗi liên kết thấy được không cần AI.

    Nhận: ``fetched`` — Shopee trả được sản phẩm; ``status`` — item_status; ``model_found`` — phân loại
    liên kết còn trên Shopee; ``is_placeholder`` — liên kết trỏ SP tạm của sale_shopee; ``is_duplicate`` —
    cùng (shop, item, model) gắn hơn một sản phẩm Odoo. Trả: một mã trong ISSUES (nặng nhất trước).
    """
    if not fetched or status in DELETED_STATUSES:
        return ISSUE_MISSING
    if not model_found:
        return ISSUE_MODEL_GONE
    if is_placeholder:
        return ISSUE_PLACEHOLDER
    if is_duplicate:
        return ISSUE_DUPLICATE
    return ISSUE_OK


def final_result(issue, ai_state, ai_verdict, applied):
    """Kết luận cuối của dòng.

    Nhận: mã lỗi (ISSUES); ``ai_state`` ("pending" / "done" / "skipped"); ``ai_verdict`` (VERDICTS hoặc
    False); ``applied`` — người dùng đã sửa liên kết từ dòng này. Trả: một mã trong RESULTS.
    Hàng / phân loại đã xoá trên Shopee là "liên kết cũ"; SP tạm, một phân loại gắn nhiều SP là map nhầm
    bất kể AI nói gì; còn lại theo AI. Dòng đã sửa là "Đã sửa" tới khi AI kiểm lại cặp mới — sau đó theo
    kết luận AI như mọi dòng khác.
    """
    if applied and ai_state != "done":
        return RESULT_FIXED
    if issue in ISSUES_STALE:
        return RESULT_STALE
    if issue != ISSUE_OK:
        return RESULT_MISMATCH
    if ai_state != "done":
        return RESULT_PENDING
    if ai_verdict == VERDICT_MISMATCH:
        return RESULT_MISMATCH
    if ai_verdict == VERDICT_MATCH:
        return RESULT_OK
    return RESULT_REVIEW
