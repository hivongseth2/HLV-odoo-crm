# -*- coding: utf-8 -*-
"""Dựng yêu cầu cho Claude xét từng liên kết "phân loại Shopee ↔ sản phẩm Odoo" có phải cùng một hàng, và đọc kết quả.

Util thuần: vào list dict, ra chuỗi / dict. Không đụng env, không gọi mạng.

Vì sao phải là AI và phải so thành phần: tên hai bên viết khác hẳn nhau (Shopee thêm chữ quảng cáo, Odoo
ghi mã + tên kỹ thuật), nên so chữ vô dụng. Lỗi hay gặp lại nằm ở thành phần: Shopee bán combo 1 pin +
1 sạc nhưng liên kết sang combo Odoo 1 máy + 1 pin + 1 sạc — tên cả hai đều có "pin", "sạc", cùng dòng
M12, nhìn qua tưởng khớp. Đơn Shopee về Odoo khi đó xuất thừa một cái máy.

Dữ liệu thật (bin/check_shopee_item_mapping.py, 10/2026) quyết định những gì KHÔNG gửi:
- Cân nặng Shopee: người đăng khai phồng để chọn vận chuyển (máy M12 trần ~1 kg ghi 7-12 kg).
- Mô tả bán Odoo: trống ở mọi sản phẩm được liên kết.
Và mô tả Shopee là của cả sản phẩm, dùng chung mọi phân loại — chỉ gửi một lần mỗi sản phẩm.
"""

import hashlib
import json

from .product_rules import VERDICT_MATCH, VERDICT_MISMATCH, VERDICT_PROBABLE

# 20 cặp một lần để câu trả lời (2 danh sách thành phần + lý do mỗi cặp) không chạm max_tokens.
BATCH_SIZE = 20
MAX_TOKENS = 32000
TEXT_MAX = 300

# System prompt KHÔNG nằm ở đây: sửa được trên Odoo (models/shopee_check_prompt.py), bản mặc định ở
# data/prompt_defaults/match_system_prompt.md. Khuôn câu trả lời (OUTPUT_SCHEMA) thì cố định trong code vì
# parse_match đọc đúng các khoá này — sửa prompt không làm vỡ được cách đọc kết quả.

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "row": {"type": "integer"},
                    "shopee_contents": {"type": "string"},
                    "odoo_contents": {"type": "string"},
                    "verdict": {"type": "string", "enum": [VERDICT_MATCH, VERDICT_PROBABLE, VERDICT_MISMATCH]},
                    "reason": {"type": "string"},
                },
                "required": ["row", "shopee_contents", "odoo_contents", "verdict", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["results"],
    "additionalProperties": False,
}


def prompt_version(text):
    """Phiên bản của một system prompt. Nhận: chuỗi (None → ""). Trả: 12 ký tự hex."""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]


def pair_fingerprint(pair, version):
    """Vân tay của một cặp, để lần kiểm sau gặp lại đúng cặp đó thì dùng lại kết luận cũ, khỏi hỏi AI.

    Nhận: dict cặp như ``match_message`` nhận (khoá ``row`` bị bỏ qua); ``version`` — prompt_version của
    prompt đang dùng. Trả: 40 ký tự hex. Đổi bất kỳ thứ gì gửi cho AI (tên, phân loại, SKU, mô tả, thành
    phần kit, sản phẩm Odoo được liên kết) hoặc SỬA PROMPT là vân tay mới — kết luận theo prompt cũ không
    được dùng lại, nếu không thì sửa prompt xong các cặp cũ vẫn giữ kết luận cũ.
    """
    data = {key: value for key, value in pair.items() if key != "row"}
    raw = json.dumps([version, data], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def match_message(shop_name, pairs):
    """Tin gửi Claude cho một lô cặp.

    Nhận: tên shop Shopee; ``pairs`` — list dict ``{"row", "shopee": {"item_id", "name", "variation", "sku",
    "description"}, "odoo": {"product_id", "code", "name", "components": [{"qty", "code", "name"}]}}``.
    Trả: chuỗi (đoạn giới thiệu + JSON ``{"shopee_descriptions": {item_id: mô tả}, "links": [...]}``). Mô tả
    gom theo item_id — mười phân loại của một sản phẩm chỉ gửi mô tả một lần. Giá trị rỗng bị bỏ;
    ``product_id`` không gửi (chỉ dùng cho vân tay).
    """
    def compact(data):
        return {key: value for key, value in data.items()
                if key not in ("product_id", "description") and value not in ("", None, False, [])}

    descriptions = {}
    links = []
    for pair in pairs:
        shopee = pair["shopee"]
        if shopee.get("description"):
            descriptions.setdefault(shopee["item_id"], shopee["description"])
        odoo = dict(pair["odoo"], components=[compact(c) for c in pair["odoo"].get("components") or []])
        links.append({"row": pair["row"], "shopee": compact(shopee), "odoo": compact(odoo)})
    payload = {"shopee_descriptions": descriptions, "links": links}
    return "Shop Shopee: %s.\nCác liên kết cần kiểm (JSON):\n%s" % (shop_name, json.dumps(payload, ensure_ascii=False))


def parse_match(text, rows):
    """Đọc câu trả lời JSON của Claude.

    Nhận: chuỗi JSON theo ``OUTPUT_SCHEMA``; ``rows`` — tập số row đã gửi. Trả: dict ``row → {"verdict",
    "reason", "shopee_contents", "odoo_contents"}`` (chuỗi cắt còn TEXT_MAX); row lạ / verdict lạ bị bỏ
    (dòng đó coi như AI bỏ sót). Lỗi: ``ValueError`` khi không phải JSON.
    """
    data = json.loads(text)
    allowed = {VERDICT_MATCH, VERDICT_PROBABLE, VERDICT_MISMATCH}
    results = {}
    for item in data["results"]:
        if item.get("row") in rows and item.get("verdict") in allowed:
            results[item["row"]] = {
                "verdict": item["verdict"],
                **{key: (item.get(key) or "").strip()[:TEXT_MAX]
                   for key in ("reason", "shopee_contents", "odoo_contents")},
            }
    return results
