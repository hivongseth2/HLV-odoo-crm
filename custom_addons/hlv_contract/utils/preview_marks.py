# -*- coding: utf-8 -*-
"""Đánh dấu chỗ của từng biến nhập trong bản xem trước, để người soạn thấy ô nào nằm ở đâu
trên hợp đồng (bấm vào chỗ đó thì nhảy tới ô nhập).

Giá trị biến được bọc bằng ký tự vùng riêng Unicode (không ai gõ ra) trước khi điền vào file
Word; sau khi file đã điền được đổi sang HTML thì thay dấu bằng <span>. Dấu đi qua docx và
escape HTML nguyên vẹn vì chỉ là ký tự thường.

mark(name, text, empty) -> chuỗi đã bọc. empty=True: chưa điền, text là nhãn biến.
marks_to_html(html) -> html với <span class="hd-pv [is-empty]" data-pv="Ten_Bien">…</span>.
Trường hợp biên: dấu bị tách mất một nửa (hiếm) thì giữ nguyên chữ, bỏ ký tự dấu thừa.
"""

import re

_FILLED = ''
_EMPTY = ''
_SEP = ''
_END = ''
_MARK_RE = re.compile('([%s%s])(\\w+)%s(.*?)%s' % (_FILLED, _EMPTY, _SEP, _END), re.DOTALL)
_STRAY_RE = re.compile('[%s%s%s%s]' % (_FILLED, _EMPTY, _SEP, _END))


def mark(name, text, empty):
    """Bọc text của biến name; empty: biến chưa có giá trị (text là nhãn để gợi chỗ cần điền)."""
    return '%s%s%s%s%s' % (_EMPTY if empty else _FILLED, name, _SEP, text, _END)


def _span(match):
    css = 'hd-pv is-empty' if match.group(1) == _EMPTY else 'hd-pv'
    return '<span class="%s" data-pv="%s">%s</span>' % (css, match.group(2), match.group(3))


def marks_to_html(html):
    """Xem docstring đầu module."""
    return _STRAY_RE.sub('', _MARK_RE.sub(_span, html))
