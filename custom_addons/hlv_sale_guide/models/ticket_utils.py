# -*- coding: utf-8 -*-
"""Hàm thuần cho ticket hướng dẫn: đặt tiêu đề, làm sạch đoạn trích, kiểm file đính kèm.

Không đụng Odoo (không env, không DB) để test được bằng Python thường.
"""

import re

TITLE_MAX = 80
QUOTE_MAX = 2000
MAX_QUOTES = 20
MAX_UPLOAD_FILES = 10
# Request của Odoo bị chặn ở 128MB (http.DEFAULT_MAX_CONTENT_LENGTH) — để dư chỗ cho phần chữ.
MAX_UPLOAD_FILE_BYTES = 50 * 1024 * 1024
MAX_UPLOAD_TOTAL_BYTES = 100 * 1024 * 1024


def _cut(text, limit):
    """Cắt text còn tối đa limit ký tự, thêm "…" khi bị cắt."""
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def ticket_title(title, body, fallback):
    """Tiêu đề ticket: title người dùng gõ; bỏ trống thì lấy dòng đầu có chữ của body.

    title, body: str hoặc None. fallback: str dùng khi cả hai đều trống (VD ticket chỉ có ảnh).
    Khoảng trắng thừa được gộp, dài quá TITLE_MAX ký tự thì cắt kèm "…".
    """
    for text in [title or ""] + (body or "").splitlines():
        text = " ".join(text.split())
        if text:
            return _cut(text, TITLE_MAX)
    return fallback


def _clean_quote(text):
    """Một đoạn bôi đen → gộp mọi khoảng trắng / xuống dòng thành một dấu cách, cắt còn QUOTE_MAX."""
    return _cut(re.sub(r"\s+", " ", text or "").strip(), QUOTE_MAX)


def join_quotes(texts):
    """Các đoạn người dùng bôi đen trong hướng dẫn → chuỗi lưu vào ticket, mỗi dòng một đoạn.

    Mỗi đoạn được gộp khoảng trắng (nên không còn xuống dòng bên trong — xuống dòng dùng làm
    dấu ngăn; JS tìm lại đoạn trên trang cũng bỏ qua khoảng trắng), cắt còn QUOTE_MAX ký tự.
    Bỏ đoạn rỗng và đoạn trùng, giữ tối đa MAX_QUOTES đoạn đầu. texts: list str (None được bỏ
    qua). Không còn đoạn nào → "".
    """
    quotes = []
    for text in texts or []:
        quote = _clean_quote(text)
        if quote and quote not in quotes:
            quotes.append(quote)
    return "\n".join(quotes[:MAX_QUOTES])


def split_quotes(text):
    """Chuỗi đã lưu bằng join_quotes → list đoạn. None / rỗng → []."""
    return [line for line in (text or "").split("\n") if line.strip()]


def check_uploads(sizes):
    """Kiểm số lượng và dung lượng file đính kèm của một tin.

    sizes: list số byte của từng file. Hợp lệ → None. Quá MAX_UPLOAD_FILES file, có file quá
    MAX_UPLOAD_FILE_BYTES, hoặc tổng quá MAX_UPLOAD_TOTAL_BYTES → ValueError (thông điệp cho
    người dùng). List rỗng là hợp lệ.
    """
    mb = 1024 * 1024
    if len(sizes) > MAX_UPLOAD_FILES:
        raise ValueError(f"Mỗi tin đính kèm tối đa {MAX_UPLOAD_FILES} file.")
    if any(size > MAX_UPLOAD_FILE_BYTES for size in sizes):
        raise ValueError(f"Mỗi file tối đa {MAX_UPLOAD_FILE_BYTES // mb}MB.")
    if sum(sizes) > MAX_UPLOAD_TOTAL_BYTES:
        raise ValueError(f"Tổng các file đính kèm tối đa {MAX_UPLOAD_TOTAL_BYTES // mb}MB.")
