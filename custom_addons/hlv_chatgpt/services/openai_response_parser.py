# -*- coding: utf-8 -*-
"""Bóc tách kết quả trả về của OpenAI Responses API.

Util thuần: chỉ đọc object được truyền vào, không đụng ``self.env``, không side effect.
"""

import re

# Chú thích nguồn của file_search, VD: 【4:0†source】. Người dùng cuối không cần thấy.
_FILE_CITATION_RE = re.compile(r"【[^】]*】")

_TEXT_CONTENT_TYPES = ("output_text", "text")


def strip_file_citations(text):
    """Xóa chú thích nguồn dạng 【...】 do file_search chèn vào.

    Nhận: chuỗi bất kỳ hoặc None.
    Trả: chuỗi đã làm sạch, đã strip hai đầu.
    Biên: None -> "".
    """
    if not text:
        return ""
    return _FILE_CITATION_RE.sub("", text).strip()


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
