# -*- coding: utf-8 -*-
"""Số thứ tự tự động của Word (danh sách đánh số / gạch đầu dòng) thành chữ, để bản xem trước
và PDF hiện đúng "ĐIỀU 1.", "a.", "-" như Word. File Word xuất ra không đụng tới: Word tự đánh số.

Labeler(numbering_root, styles_root): đọc word/numbering.xml và word/styles.xml (cây lxml hoặc
    None nếu file không có). labeler.label(p_el) -> (nhãn, thụt lề) cho một đoạn, gọi lần lượt
    theo thứ tự đoạn trong văn bản vì bộ đếm chạy theo thứ tự gọi.
    nhãn: chuỗi như "ĐIỀU 1." / "a." / "•"; đoạn không đánh số -> ''.
    thụt lề: {'indent': twips, 'first': twips} theo mức danh sách; không khai -> {}.
Trường hợp biên: numId 0 / numId không có định nghĩa / numFmt "none" -> ''. Ký tự gạch đầu dòng
font Symbol/Wingdings (vùng mã riêng U+F0xx) đổi sang ký tự Unicode gần nhất.
"""

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
_ROMAN = [(1000, 'm'), (900, 'cm'), (500, 'd'), (400, 'cd'), (100, 'c'), (90, 'xc'),
          (50, 'l'), (40, 'xl'), (10, 'x'), (9, 'ix'), (5, 'v'), (4, 'iv'), (1, 'i')]
# Gạch đầu dòng font Symbol/Wingdings Word hay dùng
_SYMBOL_BULLETS = {'': '•', '': '▪', '': '❖', '': '➢', '': '✓', '': '□',
                   '': '■', '': '➔', '': '-'}
_STYLE_DEPTH = 10


def _q(tag):
    return '{%s}%s' % (W_NS, tag)


def _val(el, tag):
    child = el.find(_q(tag)) if el is not None else None
    return child.get(_q('val')) if child is not None else None


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _roman(number):
    out = ''
    for value, letters in _ROMAN:
        while number >= value:
            out += letters
            number -= value
    return out


def _letters(number):
    """1 -> a, 26 -> z, 27 -> aa (cách Word đếm chữ)."""
    if number < 1:
        return ''
    return chr(ord('a') + (number - 1) % 26) * ((number - 1) // 26 + 1)


def format_counter(number, num_fmt):
    """Một số đếm theo kiểu numFmt của Word: decimal 3 -> '3', upperRoman 4 -> 'IV',
    lowerLetter 2 -> 'b', decimalZero 5 -> '05'. Kiểu lạ -> như decimal."""
    if num_fmt == 'upperRoman':
        return _roman(number).upper()
    if num_fmt == 'lowerRoman':
        return _roman(number)
    if num_fmt == 'upperLetter':
        return _letters(number).upper()
    if num_fmt == 'lowerLetter':
        return _letters(number)
    if num_fmt == 'decimalZero':
        return '%02d' % number
    return str(number)


def bullet_text(text):
    """Ký tự gạch đầu dòng Word lưu (có thể là mã riêng của font Symbol) -> ký tự hiển thị được."""
    out = ''.join(_SYMBOL_BULLETS.get(ch, '•' if '' <= ch <= '' else ch) for ch in text or '')
    return out or '•'


class Labeler:
    """Xem docstring đầu module."""

    def __init__(self, numbering_root, styles_root):
        self._levels = {}      # (numId, ilvl) -> định nghĩa mức
        self._starts = {}      # (numId, ilvl) -> số bắt đầu ghi đè
        self._abstract_of = {}
        self._style_numpr = {}
        self._counters = {}    # abstractNumId -> {ilvl: số hiện tại}
        if numbering_root is not None:
            self._read_numbering(numbering_root)
        if styles_root is not None:
            self._read_styles(styles_root)

    def _read_numbering(self, root):
        abstracts = {}
        for abstract in root.findall(_q('abstractNum')):
            levels = {}
            for lvl in abstract.findall(_q('lvl')):
                ind = lvl.find('%s/%s' % (_q('pPr'), _q('ind')))
                levels[_int(lvl.get(_q('ilvl')))] = {
                    'start': _int(_val(lvl, 'start'), 1),
                    'fmt': _val(lvl, 'numFmt') or 'decimal',
                    'text': _val(lvl, 'lvlText') or '',
                    'ind': ind,
                }
            abstracts[abstract.get(_q('abstractNumId'))] = levels
        for num in root.findall(_q('num')):
            num_id = num.get(_q('numId'))
            abstract_id = _val(num, 'abstractNumId')
            self._abstract_of[num_id] = abstract_id
            for ilvl, level in abstracts.get(abstract_id, {}).items():
                self._levels[(num_id, ilvl)] = level
            for override in num.findall(_q('lvlOverride')):
                start = _val(override, 'startOverride')
                if start is not None:
                    self._starts[(num_id, _int(override.get(_q('ilvl'))))] = _int(start, 1)

    def _read_styles(self, root):
        """Kiểu đoạn có gắn danh sách (Heading 1 đánh số…), kể cả kế thừa qua basedOn."""
        styles = {}
        for style in root.findall(_q('style')):
            ppr = style.find(_q('pPr'))
            numpr = ppr.find(_q('numPr')) if ppr is not None else None
            styles[style.get(_q('styleId'))] = (numpr, _val(style, 'basedOn'))
        for style_id in styles:
            current, depth = style_id, 0
            while current in styles and depth < _STYLE_DEPTH:
                numpr, parent = styles[current]
                if numpr is not None:
                    self._style_numpr[style_id] = numpr
                    break
                current, depth = parent, depth + 1

    def _numpr(self, p_el):
        ppr = p_el.find(_q('pPr'))
        if ppr is None:
            return None, 0
        numpr = ppr.find(_q('numPr'))
        style_numpr = self._style_numpr.get(_val(ppr, 'pStyle'))
        if numpr is None:
            numpr = style_numpr
        if numpr is None:
            return None, 0
        num_id = _val(numpr, 'numId')
        if num_id is None and style_numpr is not None:
            num_id = _val(style_numpr, 'numId')
        return num_id, _int(_val(numpr, 'ilvl'))

    def label(self, p_el):
        """Xem docstring đầu module."""
        num_id, ilvl = self._numpr(p_el)
        level = self._levels.get((num_id, ilvl))
        if not num_id or num_id == '0' or not level or level['fmt'] == 'none':
            return '', {}
        # Word đếm theo định nghĩa danh sách gốc: hai numId cùng abstractNum nối tiếp số của nhau
        counters = self._counters.setdefault(self._abstract_of.get(num_id), {})
        start = self._starts.get((num_id, ilvl), level['start'])
        counters[ilvl] = counters[ilvl] + 1 if ilvl in counters else start
        for deeper in [k for k in counters if k > ilvl]:
            del counters[deeper]
        if level['fmt'] == 'bullet':
            text = bullet_text(level['text'])
        else:
            text = level['text']
            for lvl_index in range(ilvl, -1, -1):
                placeholder = '%%%d' % (lvl_index + 1)
                if placeholder in text:
                    parent = self._levels.get((num_id, lvl_index)) or level
                    number = counters.get(lvl_index, parent['start'])
                    text = text.replace(placeholder, format_counter(number, parent['fmt']))
        return text, self._indent(level['ind'])

    @staticmethod
    def _indent(ind):
        if ind is None:
            return {}
        left = _int(ind.get(_q('left')) or ind.get(_q('start')))
        hanging = _int(ind.get(_q('hanging')))
        return {'indent': left, 'first': -hanging if hanging else _int(ind.get(_q('firstLine')))}
