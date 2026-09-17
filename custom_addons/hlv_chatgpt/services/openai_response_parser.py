# -*- coding: utf-8 -*-
"""Bóc tách kết quả trả về của OpenAI Responses API.

Util thuần: chỉ đọc object được truyền vào, không đụng ``self.env``, không side effect.
"""

import re

# Chú thích nguồn do file_search chèn. Người dùng cuối không cần thấy, và trên Zalo thì
# đây là rác thuần túy. OpenAI trả về ở hai dạng tùy model nên phải quét cả hai:
#   - 【4:0†source】
#   - filecite + turn0file6 + turn0file9, bọc trong ký tự Private Use Area của Unicode
_CITATION_PATTERNS = (
    re.compile(r"【[^】]*】"),
    # Ký tự Private Use Area bọc quanh chú thích; xóa trước để lộ phần chữ bên trong.
    re.compile(r"[-]"),
    re.compile(r"(?:file|video|image)cite(?:turn\d+[a-z]+\d+)*"),
    re.compile(r"turn\d+(?:file|view|search|news)\d+"),
)

# Xóa citation xong thường còn khoảng trắng thừa, và dấu câu bị đẩy ra khỏi từ.
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r" +([.,;:!?)])")

_TEXT_CONTENT_TYPES = ("output_text", "text")


def strip_file_citations(text):
    """Xóa chú thích nguồn do file_search chèn vào câu trả lời.

    Nhận: chuỗi bất kỳ hoặc None.
    Trả: chuỗi đã làm sạch, đã gom khoảng trắng thừa, đã strip hai đầu.
    Biên: None -> "". Chuỗi toàn chú thích -> "".
    """
    if not text:
        return ""
    for pattern in _CITATION_PATTERNS:
        text = pattern.sub("", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    return text.strip()


def _text_of(content_item):
    """Lấy phần text của một content block, chấp nhận cả dạng dict lồng {'value': ...}."""
    value = getattr(content_item, "text", "") or ""
    if isinstance(value, dict):
        value = value.get("value", "") or ""
    return value if isinstance(value, str) else ""


def extract_output(response):
    """Bóc text và function call từ một Response object.

    Nhận: object trả về bởi ``client.responses.create``.
    Trả: dict ``{'text': str, 'tool_calls': [{'call_id', 'name', 'arguments'}]}``.
    Biên: response rỗng hoặc cấu trúc lạ -> ``{'text': '', 'tool_calls': []}``.
    """
    text_parts = []
    tool_calls = []

    for item in (getattr(response, "output", None) or []):
        item_type = getattr(item, "type", None)

        if item_type == "message":
            for content_item in (getattr(item, "content", None) or []):
                if getattr(content_item, "type", None) in _TEXT_CONTENT_TYPES:
                    text_parts.append(_text_of(content_item))

        elif item_type == "function_call":
            # call_id (call_...) mới là id để trả kết quả về, không phải id (fc_...).
            tool_calls.append({
                "call_id": getattr(item, "call_id", None) or getattr(item, "id", None),
                "name": getattr(item, "name", "") or "",
                "arguments": getattr(item, "arguments", "") or "{}",
            })

    text = "".join(text_parts)
    if not text:
        # SDK có sẵn output_text gộp sẵn; dùng làm phương án dự phòng.
        text = getattr(response, "output_text", "") or ""

    return {"text": text, "tool_calls": tool_calls}
