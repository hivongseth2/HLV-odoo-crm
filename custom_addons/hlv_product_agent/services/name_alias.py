# -*- coding: utf-8 -*-
"""Tên gọi khác của loại hàng: kho ghi "Chữ T PVC", sale hỏi "tê"; kho ghi "Cao su non", sale hỏi
"băng tan". Bảng tự học từ dữ liệu (Claude đọc danh mục, và từ các lượt quét của trợ lý), không
trông vào sale hay kho chỉ.

Util thuần: vào chuỗi / list, ra chuỗi / list. Không đụng ``self.env``.
"""
import json
import re

from .query_format import squash_text

# Chữ in hoa đứng giữa tên thường là model / hãng ("GBH", "BOSCH") — hết phần tên loại. Trừ các
# chữ in hoa là vật liệu / chuẩn, thuộc về loại hàng ("Chữ T PVC", "Ống HDPE").
TYPE_WORDS_IN_CAPS = frozenset({
    'pvc', 'upvc', 'ppr', 'hdpe', 'pe', 'pu', 'ptfe', 'inox', 'sus', 'led', 'sds', 'ac', 'dc', 'usb', 't',
})
MAX_TYPE_WORDS = 4
MAX_ALIASES_PER_TYPE = 6
MIN_ALIAS_CHARS = 2
LEARNED_TYPES_PER_SCAN = 3

ALIAS_SYSTEM = (
    "Em giúp một công ty bán dụng cụ, máy móc, vật tư công nghiệp ở Việt Nam. Em nhận danh sách TÊN "
    "LOẠI HÀNG đúng như kho ghi (phần đầu tên sản phẩm). Với mỗi loại, liệt kê các cách sale và khách "
    "ở Việt Nam hay gọi CHÍNH loại hàng đó mà khác chữ với tên kho: tên nghề, tên miền Nam / Bắc, "
    "tên tiếng Anh hay dùng, viết tắt. Vd \"Chữ T PVC\" -> [\"tê PVC\", \"tê nhựa\"]; \"Cao su non\" -> "
    "[\"băng tan\", \"băng keo non\"]; \"Tán thép\" -> [\"đai ốc thép\", \"ê cu\"]. Chỉ ghi khi chắc là "
    "CÙNG loại hàng, không ghi loại gần giống, không ghi hãng / quy cách / màu. Không có cách gọi nào "
    "khác thì để []. Tối đa 5 cách gọi mỗi loại. Trả ĐÚNG một object JSON {\"<tên loại>\": [...]}, "
    "không chữ nào khác."
)


def leading_type(name):
    """Tên loại hàng = phần đầu tên sản phẩm, trước model / quy cách / hãng.

    Nhận: tên sản phẩm. Trả: chuỗi tối đa MAX_TYPE_WORDS từ, dừng ở từ có chữ số hoặc từ IN HOA
    (>= 2 ký tự, không phải vật liệu trong TYPE_WORDS_IN_CAPS). "Chữ T PVC 90 D BÌNH MINH" ->
    "Chữ T PVC"; "Máy khoan búa GBH 220 BOSCH" -> "Máy khoan búa"; "Tán thép M10" -> "Tán thép".
    Biên: rỗng / bắt đầu bằng số -> "".
    """
    words = []
    for word in (name or "").split():
        letters = re.sub(r"[^\w]", "", word)
        if not letters or any(ch.isdigit() for ch in letters):
            break
        if words and len(letters) >= 2 and letters.isupper() and squash_text(letters) not in TYPE_WORDS_IN_CAPS:
            break
        words.append(word.strip(",;:()"))
        if len(words) == MAX_TYPE_WORDS:
            break
    return " ".join(word for word in words if word)


def alias_prompt(type_names):
    """Tin gửi Claude cho một lô tên loại. Nhận: list chuỗi. Trả: chuỗi, mỗi loại một dòng."""
    return "Các tên loại hàng trong kho:\n" + "\n".join("- %s" % name for name in type_names)


def parse_alias_reply(text, type_names):
    """Cặp (tên loại, cách gọi khác) từ câu trả lời JSON của Claude.

    Nhận: chữ Claude trả, list tên loại đã gửi. Trả: list (tên loại, cách gọi), chỉ cho các loại có
    trong lô; bỏ cách gọi trùng tên loại sau khi bỏ dấu / khoảng trắng, quá ngắn, hoặc không phải chuỗi.
    Biên: không đọc được JSON -> [].
    """
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    sent = {squash_text(name): name for name in type_names}
    pairs = []
    for raw_type, aliases in data.items():
        type_name = sent.get(squash_text(raw_type))
        if not type_name or not isinstance(aliases, list):
            continue
        seen = {squash_text(type_name)}
        for alias in aliases[:MAX_ALIASES_PER_TYPE]:
            key = squash_text(alias) if isinstance(alias, str) else ""
            if len(key) >= MIN_ALIAS_CHARS and key not in seen:
                seen.add(key)
                pairs.append((type_name, alias.strip()))
    return pairs


def learned_pairs(scans):
    """Cặp (cách gọi, tên loại kho) học được từ các lần quet_san_pham trong MỘT lượt.

    Trợ lý quét theo cách gọi A ra rỗng, rồi quét lại (cùng điều kiện chua) theo cách gọi khác ra
    hàng: A chính là tên loại của những mã vừa ra. Lần sau quét A là có luôn.
    Nhận: list dict theo thứ tự gọi ``{'bat_dau': [str], 'chua': [str], 'names': [tên mã ra]}``.
    Trả: list (cách gọi A, tên loại kho), bỏ trùng; mỗi lần quét rỗng lấy tối đa
    LEARNED_TYPES_PER_SCAN loại hay gặp nhất trong kết quả.
    Biên: không có lần rỗng nào được cứu -> [].
    """
    pairs = []
    for index, empty in enumerate(scans):
        if empty['names'] or not empty['bat_dau']:
            continue
        chua = sorted(squash_text(term) for term in empty['chua'])
        for later in scans[index + 1:]:
            if not later['names'] or sorted(squash_text(term) for term in later['chua']) != chua:
                continue
            counts = {}
            for name in later['names']:
                kind = leading_type(name)
                if kind:
                    counts[kind] = counts.get(kind, 0) + 1
            kinds = sorted(counts, key=lambda kind: -counts[kind])[:LEARNED_TYPES_PER_SCAN]
            for term in empty['bat_dau']:
                for kind in kinds:
                    # Tên loại đã mở đầu bằng chính cách gọi này thì quét A vốn đã ra, không phải alias.
                    if (term, kind) not in pairs and not squash_text(kind).startswith(squash_text(term)):
                        pairs.append((term, kind))
            break
    return pairs
