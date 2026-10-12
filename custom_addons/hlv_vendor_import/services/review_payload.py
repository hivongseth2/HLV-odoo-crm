# -*- coding: utf-8 -*-
"""Dựng yêu cầu cho Claude duyệt ghép mã NCC ↔ sản phẩm bên mình, và đọc kết quả.

Util thuần: vào list dict, ra chuỗi / dict. Không đụng env, không gọi mạng.

Vì sao cần AI: ghép theo mã / tên ra rất nhiều cặp nhầm — cùng số model khác hãng, "05498" với
"05498A" (bộ 38 món với bộ 78 món), cùng tên khác kích thước. Dò ứng viên thì cứ dò rộng; AI loại cặp
sai, người bên mình xác nhận lần cuối.
"""

import json

VERDICT_MATCH = "match"
VERDICT_PROBABLE = "probable"
VERDICT_NONE = "none"
VERDICTS = [
    (VERDICT_MATCH, "Khớp"),
    (VERDICT_PROBABLE, "Có thể"),
    (VERDICT_NONE, "Không có"),
]
# Một lần gọi bao nhiêu dòng: đủ lớn để ít lần gọi, đủ nhỏ để câu trả lời không chạm max_tokens.
BATCH_SIZE = 25
MAX_TOKENS = 16000
REASON_MAX = 200

SYSTEM_PROMPT = """Bạn giúp phòng thu mua của một công ty thương mại dụng cụ / thiết bị ghép từng dòng trong file của nhà cung cấp (NCC) với sản phẩm trong danh mục của công ty.

Mỗi dòng có mã + tên hàng theo cách NCC gọi, kèm vài sản phẩm ỨNG VIÊN do máy dò theo mã / tên (dò rộng, phần lớn có thể sai). Với từng dòng, chọn đúng MỘT ứng viên là CÙNG một mặt hàng, hoặc kết luận không có.

Cùng một mặt hàng nghĩa là:
- Cùng hãng. NCC đã cho biết hãng thì ứng viên hãng khác là sai, dù trùng số model.
- Cùng model: phần số của mã trùng nhau. Hậu tố chữ của NCC (A, S, U, M, L…) thường là biến thể khác (cỡ, số món, điện áp) — ứng viên thiếu / khác hậu tố chỉ được coi là cùng hàng khi tên mô tả đúng cùng thông số.
- Cùng thông số khi tên có ghi: kích thước, tải trọng, công suất, điện áp, số món trong bộ, dải đo. Một thông số khác là khác hàng.
- Đơn vị tính khác nhau (cái / bộ / hộp) không tự làm sai, nhưng phải nêu trong lý do.

Kết luận cho từng dòng:
- "match": chắc chắn cùng hàng.
- "probable": nhiều khả năng cùng hàng nhưng còn một điểm chưa chắc (thiếu thông số để so, hậu tố khác mà tên gần giống). Người sẽ kiểm lại.
- "none": không ứng viên nào là cùng hàng, hoặc không có ứng viên. product_id = 0.
Không chắc thì chọn "probable" hoặc "none", không bao giờ "match".

product_id chỉ được là id của một ứng viên của CHÍNH dòng đó. reason: một câu tiếng Việt ngắn (dưới 25 từ) nói điểm quyết định, vd "Trùng model 97813A và tải 3 tấn" hoặc "Ứng viên là bộ 38 món, NCC là bộ 78 món". Trả kết quả cho mọi dòng, dùng đúng số row đã cho."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "row": {"type": "integer"},
                    "product_id": {"type": "integer"},
                    "verdict": {"type": "string", "enum": [VERDICT_MATCH, VERDICT_PROBABLE, VERDICT_NONE]},
                    "reason": {"type": "string"},
                },
                "required": ["row", "product_id", "verdict", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["results"],
    "additionalProperties": False,
}


def review_message(vendor, brand, rows):
    """Tin gửi Claude cho một lô dòng.

    Nhận: tên NCC; hãng NCC bán (có thể rỗng); ``rows`` — list dict ``{"row", "code", "name", "name_alt",
    "uom", "candidates": [{"id", "code", "name", "uom"}]}``.
    Trả: chuỗi (đoạn giới thiệu + JSON các dòng). Khoá rỗng bị bỏ khỏi JSON cho gọn.
    """
    def compact(item):
        return {key: value for key, value in item.items() if value not in ("", None, [])}

    payload = [compact(dict(row, candidates=[compact(c) for c in row["candidates"]])) for row in rows]
    intro = "NCC: %s." % vendor
    if brand:
        intro += " Hãng NCC này bán: %s." % brand
    return "%s\nCác dòng cần ghép (JSON):\n%s" % (intro, json.dumps(payload, ensure_ascii=False))


def parse_review(text, rows):
    """Đọc câu trả lời JSON của Claude, chỉ giữ kết luận hợp lệ.

    Nhận: chuỗi JSON theo ``OUTPUT_SCHEMA``; ``rows`` đã gửi (để biết ứng viên của từng dòng).
    Trả: dict ``row → {"product_id": int|False, "verdict", "reason"}``. Dòng Claude bỏ sót thì không có
    trong dict. product_id không thuộc ứng viên của dòng đó → coi như "none" (không tin id bịa).
    Lỗi: ``ValueError`` khi không phải JSON đúng dạng.
    """
    data = json.loads(text)
    allowed = {row["row"]: {c["id"] for c in row["candidates"]} for row in rows}
    results = {}
    for item in data["results"]:
        row = item.get("row")
        if row not in allowed:
            continue
        product_id = item.get("product_id") or False
        verdict = item.get("verdict")
        reason = (item.get("reason") or "").strip()[:REASON_MAX]
        if verdict not in (VERDICT_MATCH, VERDICT_PROBABLE) or product_id not in allowed[row]:
            if verdict != VERDICT_NONE:
                reason = ("AI chọn sản phẩm ngoài danh sách ứng viên. " + reason)[:REASON_MAX]
            product_id, verdict = False, VERDICT_NONE
        results[row] = {"product_id": product_id, "verdict": verdict, "reason": reason}
    return results
