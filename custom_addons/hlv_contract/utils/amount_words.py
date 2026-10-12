# -*- coding: utf-8 -*-
"""Đổi số tiền VND thành chữ tiếng Việt.

Đầu vào: số (int/float/Decimal/str số). Được làm tròn về đồng nguyên trước khi đọc.
Đầu ra: chuỗi đã viết hoa chữ cái đầu và kết thúc bằng "đồng", ví dụ 35832000 ->
"Ba mươi lăm triệu tám trăm ba mươi hai nghìn đồng".
Trường hợp biên: 0 -> "Không đồng"; số âm -> thêm "Âm"; None/'' -> "Không đồng".
"""

from decimal import Decimal, ROUND_HALF_UP

_DIGITS = ['không', 'một', 'hai', 'ba', 'bốn', 'năm', 'sáu', 'bảy', 'tám', 'chín']
# Nhóm 3 chữ số đi từ phải sang trái: đồng, nghìn, triệu, tỷ, nghìn tỷ, triệu tỷ
_SCALES = ['', 'nghìn', 'triệu', 'tỷ', 'nghìn tỷ', 'triệu tỷ']


def _read_group(group, has_higher):
    """Đọc nhóm 3 chữ số (1..999). has_higher: có nhóm lớn hơn khác 0 đứng trước,
    khi đó trăm = 0 đọc "không trăm", đơn vị lẻ đọc "lẻ" (1 000 005 -> "một triệu không trăm lẻ năm")."""
    hundreds, rest = divmod(group, 100)
    tens, units = divmod(rest, 10)
    words = []
    if hundreds:
        words += [_DIGITS[hundreds], 'trăm']
    elif has_higher:
        words += ['không', 'trăm']
    if tens == 0:
        if units:
            if hundreds or has_higher:
                words.append('lẻ')
            words.append(_DIGITS[units])
        return words
    if tens == 1:
        words.append('mười')
    else:
        words += [_DIGITS[tens], 'mươi']
    if units == 0:
        return words
    if units == 1 and tens > 1:
        words.append('mốt')
    elif units == 4 and tens > 1:
        words.append('tư')
    elif units == 5:
        words.append('lăm')
    else:
        words.append(_DIGITS[units])
    return words


def _read_integer(n):
    if n == 0:
        return 'không'
    groups = []
    while n:
        n, g = divmod(n, 1000)
        groups.append(g)
    parts = []
    for idx in range(len(groups) - 1, -1, -1):
        g = groups[idx]
        if g == 0:
            continue
        has_higher = any(groups[idx + 1:])
        words = _read_group(g, has_higher)
        scale = _SCALES[idx] if idx < len(_SCALES) else ''
        if scale:
            words.append(scale)
        parts.append(' '.join(words))
    return ' '.join(parts)


def amount_in_words_vi(amount):
    """Xem docstring đầu module."""
    if amount in (None, ''):
        return 'Không đồng'
    value = int(Decimal(str(amount)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if value == 0:
        return 'Không đồng'
    prefix = 'Âm ' if value < 0 else ''
    text = prefix + _read_integer(abs(value)) + ' đồng'
    return text[0].upper() + text[1:]
