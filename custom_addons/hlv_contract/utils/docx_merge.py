# -*- coding: utf-8 -*-
"""Điền MERGEFIELD trong file .docx (bytes -> bytes), không cần Word hay LibreOffice.

Word lưu trường trộn dạng field phức (fldChar begin/separate/end + instrText) hoặc
fldSimple. Điền ở thân văn bản và đầu/chân trang (word/header*.xml, footer*.xml).

fill_docx(docx_bytes, values, line_count=0, prune_empty_rows=True, styles=None):
    Định dạng chữ của giá trị điền vào: trường không tự mang định dạng (mẫu tạo bằng code / Word
    không bôi đậm trường) thì lấy theo chữ đứng ngay trước trong cùng đoạn ("Số: «So_Hop_Dong»"
    nghiêng như "Số:"); styles {tên: {'b','i','u','caps': bool}} bật thêm kiểu cho từng biến
    (cấu hình "Kiểu chữ" của biến), áp ở mọi chỗ biến xuất hiện.
    values: dict {tên_trường: chuỗi}. Trường có trong file nhưng thiếu khoá trong
    values được giữ nguyên dạng «Tên» để lộ ra khi soát mẫu. Khoá có giá trị '' thì
    xoá sạch chữ trong trường. Giá trị có '\\n' được xuống dòng (w:br).
    line_count: số dòng hàng thực tế. Nếu lớn hơn số dòng hàng có trong bảng mẫu, dòng
    hàng cuối (dòng chứa Ten_Hang_N... lớn nhất) được nhân bản và đánh số tiếp; ô số thứ
    tự ghi đúng bằng N cũng được đổi theo. Mẫu không có dòng hàng thì bỏ qua.
    prune_empty_rows: xoá dòng hàng (dòng bảng có biến Ten_Hang_N, DVT_N...) mà mọi biến
    đều rỗng, ví dụ dòng 7..10 khi hợp đồng chỉ có 6 mặt hàng. Dòng bảng khác giữ nguyên
    dù biến rỗng (bảng bố cục thông tin bên mua không bị mất dòng).
    Trả về bytes của file .docx mới.
list_merge_fields(docx_bytes):
    Trả về list tên trường MERGEFIELD (thân + đầu/chân trang) theo thứ tự xuất hiện, không
    trùng — thứ tự này là thứ tự ô nhập trên hợp đồng.
Trường hợp biên: file hỏng -> ValueError. Field lồng trong field chỉ xử lý field ngoài cùng.
"""

import copy
import re
import zipfile
from io import BytesIO

from lxml import etree

from .contract_vars import LINE_FIELDS, LINE_VARIABLE_RE
from .docx_io import DOCUMENT_PART, W_NS, XML_SPACE, merge_field_name, read_xml_parts

_HEADER_FOOTER_RE = re.compile(r'^word/(header|footer)\d*\.xml$')


def _q(tag):
    return '{%s}%s' % (W_NS, tag)


def _is_fillable_part(name):
    return name == DOCUMENT_PART or bool(_HEADER_FOOTER_RE.match(name))


def _top_level_fields(element):
    """Các field ngoài cùng trong element: list dict {name, texts} với texts là danh sách
    w:t nằm trong phần kết quả hiển thị của field. Chỉ lấy MERGEFIELD."""
    fields = []
    stack = []
    for run in element.iter(_q('r')):
        for child in run:
            tag = child.tag
            if tag == _q('fldChar'):
                kind = child.get(_q('fldCharType'))
                if kind == 'begin':
                    stack.append({'instr': '', 'stage': 'instr', 'texts': [], 'begin': run})
                elif kind == 'separate' and stack:
                    stack[-1]['stage'] = 'result'
                elif kind == 'end' and stack:
                    done = stack.pop()
                    if not stack:
                        fields.append({'name': merge_field_name(done['instr']), 'texts': done['texts'],
                                       'begin': done['begin']})
            elif tag == _q('instrText') and stack and stack[-1]['stage'] == 'instr':
                stack[-1]['instr'] += child.text or ''
            elif tag == _q('t') and stack and stack[-1]['stage'] == 'result':
                stack[-1]['texts'].append(child)
    for simple in element.iter(_q('fldSimple')):
        fields.append({'name': merge_field_name(simple.get(_q('instr'))),
                       'texts': list(simple.iter(_q('t'))), 'begin': simple})
    return [f for f in fields if f['name']]


def _set_text(t_element, value):
    """Ghi value vào w:t; mỗi '\\n' thành một w:br + w:t mới trong cùng run để giữ định dạng."""
    lines = (value or '').split('\n')
    t_element.text = lines[0]
    t_element.set(XML_SPACE, 'preserve')
    anchor = t_element
    for line in lines[1:]:
        br = etree.Element(_q('br'))
        anchor.addnext(br)
        new_t = etree.Element(_q('t'))
        new_t.text = line
        new_t.set(XML_SPACE, 'preserve')
        br.addnext(new_t)
        anchor = new_t


_STYLE_TAGS = {'b': 'b', 'i': 'i', 'u': 'u', 'caps': 'caps'}
_LOOK_TAGS = {'b', 'i', 'u', 'caps', 'sz', 'strike', 'color', 'highlight'}


def _has_look(rpr):
    """rPr có định dạng nhìn thấy được (đậm, nghiêng, cỡ chữ...) hay chỉ có font / trống."""
    return rpr is not None and any(etree.QName(child).localname in _LOOK_TAGS for child in rpr)


def _style_source(field):
    """rPr của chữ đứng ngay trước trường trong cùng đoạn (không tính chữ trống), hoặc None."""
    begin = field['begin']
    paragraph = next((a for a in begin.iterancestors() if a.tag == _q('p')), None)
    if paragraph is None:
        return None
    runs = list(paragraph.iter(_q('r')))
    index = runs.index(begin) if begin in runs else len(runs)
    for run in reversed(runs[:index]):
        if any((t.text or '').strip() for t in run.findall(_q('t'))):
            return run.find(_q('rPr'))
    return None


def _apply_style(rpr, style):
    """Bật/tắt đậm, nghiêng, gạch chân, in hoa trên rPr theo style {'b','i','u','caps'}."""
    for key, tag in _STYLE_TAGS.items():
        if key not in style:
            continue
        for old in rpr.findall(_q(tag)):
            rpr.remove(old)
        if style[key]:
            node = etree.SubElement(rpr, _q(tag))
            if tag == 'u':
                node.set(_q('val'), 'single')


def _style_field(field, style):
    """Định dạng phần giá trị của trường: kế thừa chữ đứng trước nếu trường không tự có định dạng,
    rồi áp style của biến. Ghi rPr giống nhau vào mọi run giá trị."""
    runs = []
    for t_el in field['texts']:
        run = t_el.getparent()
        if run.tag == _q('r') and run not in runs:
            runs.append(run)
    if not runs:
        return
    rpr = runs[0].find(_q('rPr'))
    if not _has_look(rpr):
        source = _style_source(field)
        if _has_look(source):
            rpr = copy.deepcopy(source)
    if style:
        rpr = copy.deepcopy(rpr) if rpr is not None else etree.Element(_q('rPr'))
        _apply_style(rpr, style)
    if rpr is None:
        return
    for run in runs:
        old = run.find(_q('rPr'))
        if old is not None:
            run.remove(old)
        run.insert(0, copy.deepcopy(rpr))


def _fill_element(element, values, styles=None):
    for field in _top_level_fields(element):
        name = field['name']
        if name not in values or not field['texts']:
            continue
        _style_field(field, (styles or {}).get(name))
        for extra in field['texts'][1:]:
            extra.text = ''
        _set_text(field['texts'][0], values[name])


def _line_indexes(row):
    """Tập số thứ tự dòng hàng xuất hiện trong một dòng bảng (Ten_Hang_3 -> 3)."""
    indexes = set()
    for field in _top_level_fields(row):
        match = LINE_VARIABLE_RE.match(field['name'])
        if match:
            indexes.add(int(match.group(2)))
    return indexes


def _is_empty_line_row(row, values):
    """Dòng hàng thừa: có biến dòng hàng và mọi biến đều rỗng. Biến dòng hàng không có trong
    values (mẫu có nhiều dòng hơn số mặt hàng) cũng tính là rỗng."""
    fields = _top_level_fields(row)
    if not any(LINE_VARIABLE_RE.match(f['name']) for f in fields):
        return False
    return all(values.get(f['name'], '' if LINE_VARIABLE_RE.match(f['name']) else None) == ''
               for f in fields)


def _renumber_row(row, old, new):
    pattern = re.compile(r'\b(%s)_%d\b' % ('|'.join(LINE_FIELDS), old))
    replacement = r'\g<1>_%d' % new
    for instr in row.iter(_q('instrText')):
        instr.text = pattern.sub(replacement, instr.text or '')
    for simple in row.iter(_q('fldSimple')):
        simple.set(_q('instr'), pattern.sub(replacement, simple.get(_q('instr')) or ''))
    # Ô STT là chữ tĩnh trong mẫu, đổi theo để dòng nhân bản không trùng số
    for t_el in row.iter(_q('t')):
        if (t_el.text or '').strip() == str(old):
            t_el.text = t_el.text.replace(str(old), str(new))


def _expand_line_rows(root, line_count):
    """Nhân bản dòng hàng cuối của bảng mẫu cho đủ line_count dòng. Mẫu không có dòng
    hàng (ví dụ hợp đồng nguyên tắc) thì không làm gì."""
    prototype, last_index = None, 0
    for row in root.iter(_q('tr')):
        indexes = _line_indexes(row)
        if len(indexes) == 1:
            index = indexes.pop()
            if index > last_index:
                prototype, last_index = row, index
    if prototype is None:
        return
    anchor = prototype
    for index in range(last_index + 1, line_count + 1):
        clone = copy.deepcopy(prototype)
        _renumber_row(clone, last_index, index)
        anchor.addnext(clone)
        anchor = clone


def fill_docx(docx_bytes, values, line_count=0, prune_empty_rows=True, styles=None):
    """Xem docstring đầu module."""
    parts = read_xml_parts(docx_bytes, _is_fillable_part)
    for name, root in parts.items():
        if name == DOCUMENT_PART:
            _expand_line_rows(root, line_count)
            if prune_empty_rows:
                for row in list(root.iter(_q('tr'))):
                    if _is_empty_line_row(row, values):
                        row.getparent().remove(row)
        _fill_element(root, values, styles)

    out = BytesIO()
    with zipfile.ZipFile(BytesIO(docx_bytes)) as zin, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename in parts:
                data = etree.tostring(parts[item.filename], xml_declaration=True, encoding='UTF-8', standalone=True)
            else:
                data = zin.read(item.filename)
            zout.writestr(item, data)
    return out.getvalue()


def list_merge_fields(docx_bytes):
    """Xem docstring đầu module."""
    parts = read_xml_parts(docx_bytes, _is_fillable_part)
    names = []
    for root in parts.values():
        for field in _top_level_fields(root):
            if field['name'] not in names:
                names.append(field['name'])
    return names
