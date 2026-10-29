# -*- coding: utf-8 -*-
"""Kiểm HTML Claude gửi cho bảng nổi (show_panel) trước khi đưa lên trang.

Bảng chạy trong iframe khoá script (an toàn với chữ lạ lấy từ web). Claude hay quen tay dựng
biểu đồ bằng JavaScript / canvas: bị chặn thì bảng trắng trơn mà không ai biết vì sao. Bắt từ
đầu, trả lỗi để Claude dựng lại bằng HTML + SVG tĩnh.

Util thuần: vào chuỗi, ra list chuỗi. Không đụng ``self.env``.
"""
import re

_BLOCKED = [
    (re.compile(r"<\s*script\b", re.I), "thẻ <script>"),
    (re.compile(r"<\s*canvas\b", re.I), "thẻ <canvas> (cần script mới vẽ được)"),
    (re.compile(r"<\s*(iframe|object|embed)\b", re.I), "nhúng trang / plugin (<iframe>, <object>, <embed>)"),
    (re.compile(r"\son[a-z]+\s*=", re.I), "thuộc tính sự kiện on...= (onclick, onload...)"),
    (re.compile(r"javascript\s*:", re.I), "link javascript:"),
]


def panel_html_problems(html):
    """Những thứ trong HTML sẽ không chạy trong bảng (iframe khoá script).

    Nhận: chuỗi HTML. Trả: list mô tả ngắn từng loại vi phạm, theo thứ tự _BLOCKED.
    Biên: chuỗi rỗng / None -> [].
    """
    html = html or ""
    return [label for pattern, label in _BLOCKED if pattern.search(html)]
