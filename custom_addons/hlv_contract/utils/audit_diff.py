# -*- coding: utf-8 -*-
"""So sánh trước/sau một lần sửa hợp đồng thành các dòng chữ cho nhật ký.

diff_values(old, new, labels) -> list chữ, mỗi thay đổi một dòng:
    'Tên bên mua: “Công ty A” → “Công ty B”'. old/new: dict {khoá: giá trị};
    labels: {khoá: nhãn}, khoá không có nhãn thì hiện chính khoá. Giá trị rỗng/None/False hiện
    "(trống)". Không đổi gì -> [].
diff_lines(old, new) -> list chữ về hàng hoá: thêm, bỏ, đổi số lượng/đơn giá/ĐVT.
    old/new: list dict {name, uom, quantity, price}. Ghép theo tên hàng (trùng tên thì ghép
    lần lượt theo thứ tự). Không đổi gì -> [].
Trường hợp biên: chuỗi dài quá 120 ký tự bị cắt "…" để nhật ký đọc được.
"""

from .contract_vars import format_money, format_number

_MAX_TEXT = 120
_EMPTY = '(trống)'


def _is_empty(value):
    # So bằng is: 0 == False trong Python, mà số 0 (VAT 0%) là giá trị thật, không phải trống
    return value is None or value is False or value == ''


def _show(value):
    if _is_empty(value):
        return _EMPTY
    text = ' '.join(str(value).split())
    return '“%s”' % (text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT - 1] + '…')


def diff_values(old, new, labels):
    """Xem docstring đầu module."""
    old = old or {}
    new = new or {}
    keys = list(old) + [k for k in new if k not in old]
    lines = []
    for key in keys:
        before, after = old.get(key), new.get(key)
        if (_is_empty(before) and _is_empty(after)) or before == after:
            continue
        lines.append('%s: %s → %s' % (labels.get(key, key), _show(before), _show(after)))
    return lines


def _line_text(line):
    return '%s × %s %s, giá %s' % (line.get('name') or '', format_number(line.get('quantity')),
                                    line.get('uom') or '', format_money(line.get('price')))


def diff_lines(old, new):
    """Xem docstring đầu module."""
    remaining = list(old or [])
    lines = []
    for line in new or []:
        match = next((o for o in remaining if o.get('name') == line.get('name')), None)
        if match is None:
            lines.append('Thêm hàng: %s' % _line_text(line))
            continue
        remaining.remove(match)
        changes = []
        if float(match.get('quantity') or 0) != float(line.get('quantity') or 0):
            changes.append('SL %s → %s' % (format_number(match.get('quantity')), format_number(line.get('quantity'))))
        if format_money(match.get('price')) != format_money(line.get('price')):
            changes.append('giá %s → %s' % (format_money(match.get('price')), format_money(line.get('price'))))
        if (match.get('uom') or '') != (line.get('uom') or ''):
            changes.append('ĐVT %s → %s' % (_show(match.get('uom')), _show(line.get('uom'))))
        if changes:
            lines.append('Sửa hàng %s: %s' % (line.get('name'), ', '.join(changes)))
    lines += ['Bỏ hàng: %s' % _line_text(line) for line in remaining]
    return lines
