# -*- coding: utf-8 -*-
"""Đọc và ghi .docx bằng lớp trung gian "blocks" (list dict thuần, không phụ thuộc Odoo).

Cấu trúc blocks:
  đoạn:  {'type': 'p', 'align': 'left'|'center'|'right'|'justify', 'runs': [run, ...],
          'indent': twips lề trái, 'first': twips dòng đầu (âm = treo), 'after': twips cách dưới}
  bảng:  {'type': 'table', 'rows': [[cell, ...], ...], 'borders': bool,
          'widths': [độ rộng tương đối từng cột] hoặc None (chia đều)}
         cell = {'span': int, 'paras': [đoạn, ...]}   (span = số cột gộp)
  run:   {'text': str, 'b': bool, 'i': bool, 'u': bool, 'sz': nửa-point hoặc None}
         {'field': 'Ten_Ben_Mua'}   trường MERGEFIELD
         {'br': True}               xuống dòng mềm
  Các khoá indent/first/after/borders/widths/sz đều tuỳ chọn.

build_docx(blocks) -> bytes .docx khổ A4, font Times New Roman 13pt.
read_docx(docx_bytes, keep_fields=True) -> blocks.
  keep_fields=True : trường MERGEFIELD thành {'field': name} (dùng để soạn mẫu).
  keep_fields=False: lấy chữ hiển thị của trường (dùng cho file đã điền, để xuất PDF).
read_xml_parts(docx_bytes, names) -> {tên part: cây lxml}; file hỏng -> ValueError.
merge_field_name(instr) -> tên trường từ mã field Word, hoặc None.
Trường hợp biên: đoạn trống vẫn được giữ để giữ khoảng cách; ô bảng rỗng vẫn có một
đoạn trống; tab đổi thành w:tab; hình ảnh, bảng lồng trong ô bị bỏ qua.
"""

import re
import zipfile
from io import BytesIO
from xml.sax.saxutils import escape

from lxml import etree

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'
DOCUMENT_PART = 'word/document.xml'
PAGE_TEXT_WIDTH_TWIPS = 9354
FORMAT_KEYS = ('b', 'i', 'u', 'sz')
_NBSP = '\xa0'
_MERGE_RE = re.compile(r'^\s*MERGEFIELD\s+"?([^"\s\\]+)"?', re.IGNORECASE)
_NO_BORDER = ('nil', 'none')
_ALIGN_TO_JC = {'left': 'left', 'center': 'center', 'right': 'right', 'justify': 'both'}
_JC_TO_ALIGN = {'left': 'left', 'start': 'left', 'center': 'center', 'right': 'right',
                'end': 'right', 'both': 'justify', 'distribute': 'justify'}

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '</Types>')
_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '</Relationships>')
_DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '</Relationships>')
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="%s"><w:docDefaults><w:rPrDefault><w:rPr>'
    '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman" w:eastAsia="Times New Roman"/>'
    '<w:sz w:val="26"/><w:szCs w:val="26"/><w:lang w:val="vi-VN"/>'
    '</w:rPr></w:rPrDefault><w:pPrDefault/></w:docDefaults>'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
    '</w:styles>') % W_NS
# Lề A4: trên/dưới 2 cm, trái 2,5 cm, phải 2 cm, cùng lề với khổ giấy PDF (data/report_data.xml).
# Vùng chữ = 11906 - 1418 - 1134 = PAGE_TEXT_WIDTH_TWIPS
_SECT_PR = (
    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
    '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1418" w:header="567" w:footer="567" w:gutter="0"/>'
    '</w:sectPr>')


def _q(tag):
    return '{%s}%s' % (W_NS, tag)


def merge_field_name(instr):
    """Tên trường từ mã field Word, ví dụ ' MERGEFIELD  Ten_Ben_Mua \\* MERGEFORMAT ' -> 'Ten_Ben_Mua'.
    Không phải MERGEFIELD (PAGE, HYPERLINK...) hoặc rỗng -> None."""
    match = _MERGE_RE.match(instr or '')
    return match.group(1) if match else None


def read_xml_parts(docx_bytes, names=None):
    """Đọc các part XML trong file .docx. names: list tên part hoặc hàm lọc tên; None =
    chỉ word/document.xml. Trả về dict {tên: cây lxml} theo thứ tự tên trong file.
    File không phải zip, thiếu document.xml hoặc XML hỏng -> ValueError."""
    try:
        with zipfile.ZipFile(BytesIO(docx_bytes)) as zf:
            available = zf.namelist()
            if DOCUMENT_PART not in available:
                raise ValueError('File .docx không có word/document.xml')
            if names is None:
                wanted = [DOCUMENT_PART]
            elif callable(names):
                wanted = [n for n in available if names(n)]
            else:
                wanted = [n for n in names if n in available]
            return {name: etree.fromstring(zf.read(name)) for name in wanted}
    except (zipfile.BadZipFile, etree.XMLSyntaxError) as err:
        raise ValueError('File không phải .docx hợp lệ (%s)' % err)


# ---------- ghi ----------

def _rpr(run):
    parts = []
    if run.get('b'):
        parts.append('<w:b/>')
    if run.get('i'):
        parts.append('<w:i/>')
    if run.get('u'):
        parts.append('<w:u w:val="single"/>')
    if run.get('sz'):
        parts.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (run['sz'], run['sz']))
    return '<w:rPr>%s</w:rPr>' % ''.join(parts) if parts else ''


def _text_runs(text, rpr):
    """Tách tab thành w:tab để Word hiển thị đúng."""
    pieces = []
    for idx, chunk in enumerate(text.split('\t')):
        if idx:
            pieces.append('<w:r>%s<w:tab/></w:r>' % rpr)
        if chunk:
            pieces.append('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, escape(chunk)))
    return ''.join(pieces)


def _field_runs(name, rpr):
    """Field MERGEFIELD dạng phức, cùng cấu trúc Word tự tạo khi chèn trường trộn."""
    return (
        '<w:r>%(rpr)s<w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r>%(rpr)s<w:instrText xml:space="preserve"> MERGEFIELD %(name)s </w:instrText></w:r>'
        '<w:r>%(rpr)s<w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:r>%(rpr)s<w:t xml:space="preserve">«%(name)s»</w:t></w:r>'
        '<w:r>%(rpr)s<w:fldChar w:fldCharType="end"/></w:r>'
    ) % {'rpr': rpr, 'name': escape(name)}


def _ppr(para):
    jc = _ALIGN_TO_JC.get(para.get('align') or 'left', 'left')
    after = para.get('after')
    spacing = '<w:spacing w:after="%d"/>' % (after if after is not None else 60)
    indent = ''
    if para.get('indent') or para.get('first'):
        first = para.get('first') or 0
        attr = 'w:hanging="%d"' % -first if first < 0 else 'w:firstLine="%d"' % first
        indent = '<w:ind w:left="%d" %s/>' % (para.get('indent') or 0, attr)
    return '<w:pPr>%s%s<w:jc w:val="%s"/></w:pPr>' % (spacing, indent, jc)


def _para_xml(para):
    out = ['<w:p>', _ppr(para)]
    for run in para.get('runs') or []:
        if run.get('br'):
            out.append('<w:r><w:br/></w:r>')
        elif run.get('field'):
            out.append(_field_runs(run['field'], _rpr(run)))
        elif run.get('text'):
            out.append(_text_runs(run['text'], _rpr(run)))
    out.append('</w:p>')
    return ''.join(out)


def _column_widths(table):
    """Độ rộng từng cột (twips) theo tỉ lệ widths, tổng bằng bề rộng vùng chữ."""
    rows = table.get('rows') or []
    columns = max((sum(int(c.get('span') or 1) for c in row) for row in rows), default=1) or 1
    widths = table.get('widths') or []
    if len(widths) != columns or not sum(widths):
        widths = [1] * columns
    total = float(sum(widths))
    return [int(PAGE_TEXT_WIDTH_TWIPS * w / total) for w in widths]


def _table_xml(table):
    col_widths = _column_widths(table)
    edge_val = 'single' if table.get('borders', True) else 'nil'
    border = ''.join('<w:%s w:val="%s" w:sz="4" w:space="0" w:color="000000"/>' % (edge, edge_val)
                     for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'))
    out = ['<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:tblBorders>%s</w:tblBorders>'
           '<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>' % (sum(col_widths), border)]
    out += ['<w:gridCol w:w="%d"/>' % w for w in col_widths]
    out.append('</w:tblGrid>')
    for row in table.get('rows') or []:
        out.append('<w:tr>')
        col = 0
        for cell in row:
            span = int(cell.get('span') or 1)
            width = sum(col_widths[col:col + span]) or col_widths[-1]
            col += span
            grid = '<w:gridSpan w:val="%d"/>' % span if span > 1 else ''
            paras = cell.get('paras') or [{'type': 'p', 'runs': []}]
            out.append('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/>%s</w:tcPr>%s</w:tc>'
                       % (width, grid, ''.join(_para_xml(p) for p in paras)))
        out.append('</w:tr>')
    out.append('</w:tbl>')
    return ''.join(out)


def build_docx(blocks):
    """Xem docstring đầu module. Trả về bytes .docx."""
    body = []
    for idx, block in enumerate(blocks):
        if block.get('type') == 'table':
            body.append(_table_xml(block))
            # Sau bảng phải có đoạn nếu là cuối văn bản hoặc kề bảng khác, nếu không Word
            # báo file lỗi hoặc gộp hai bảng làm một
            if idx + 1 == len(blocks) or blocks[idx + 1].get('type') == 'table':
                body.append('<w:p/>')
        else:
            body.append(_para_xml(block))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="%s"><w:body>%s%s</w:body></w:document>'
    ) % (W_NS, ''.join(body), _SECT_PR)
    out = BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', _CONTENT_TYPES)
        zf.writestr('_rels/.rels', _ROOT_RELS)
        zf.writestr(DOCUMENT_PART, document)
        zf.writestr('word/styles.xml', _STYLES)
        zf.writestr('word/_rels/document.xml.rels', _DOC_RELS)
    return out.getvalue()


# ---------- đọc ----------

def _flag(rpr, tag):
    if rpr is None:
        return False
    node = rpr.find(_q(tag))
    if node is None:
        return False
    return node.get(_q('val')) not in ('0', 'false', 'none')


def _int_attr(node, attr):
    if node is None:
        return None
    try:
        return int(node.get(_q(attr)))
    except (TypeError, ValueError):
        return None


def _run_format(rpr):
    return {
        'b': _flag(rpr, 'b'),
        'i': _flag(rpr, 'i'),
        'u': _flag(rpr, 'u'),
        'sz': _int_attr(rpr.find(_q('sz')) if rpr is not None else None, 'val'),
    }


def _para_format(p_el):
    ppr = p_el.find(_q('pPr'))
    fmt = {'align': 'left'}
    if ppr is None:
        return fmt
    jc = ppr.find(_q('jc'))
    if jc is not None:
        fmt['align'] = _JC_TO_ALIGN.get(jc.get(_q('val')), 'left')
    ind = ppr.find(_q('ind'))
    if ind is not None:
        fmt['indent'] = _int_attr(ind, 'left') or _int_attr(ind, 'start') or 0
        hanging = _int_attr(ind, 'hanging')
        fmt['first'] = -hanging if hanging else (_int_attr(ind, 'firstLine') or 0)
    after = _int_attr(ppr.find(_q('spacing')), 'after')
    if after is not None:
        fmt['after'] = after
    return fmt


def _read_paragraph(p_el, keep_fields):
    runs = []
    stack = []  # field phức đang mở: {'instr', 'stage', 'merge'}
    simple_done = set()
    for run in p_el.iter(_q('r')):
        parent = run.getparent()
        if parent.tag == _q('fldSimple'):
            name = merge_field_name(parent.get(_q('instr')))
            if keep_fields and name:
                if id(parent) not in simple_done:
                    simple_done.add(id(parent))
                    runs.append({'field': name})
                continue
        flags = _run_format(run.find(_q('rPr')))
        for child in run:
            tag = child.tag
            if tag == _q('fldChar'):
                kind = child.get(_q('fldCharType'))
                if kind == 'begin':
                    stack.append({'instr': '', 'stage': 'instr', 'merge': False})
                elif kind == 'separate' and stack:
                    top = stack[-1]
                    top['stage'] = 'result'
                    name = merge_field_name(top['instr'])
                    top['merge'] = bool(keep_fields and name)
                    if top['merge']:
                        runs.append({'field': name})
                elif kind == 'end' and stack:
                    stack.pop()
            elif tag == _q('instrText') and stack and stack[-1]['stage'] == 'instr':
                stack[-1]['instr'] += child.text or ''
            elif any(e['merge'] or e['stage'] == 'instr' for e in stack):
                continue
            elif tag == _q('t') and child.text:
                runs.append(dict(flags, text=child.text))
            elif tag == _q('tab'):
                runs.append(dict(flags, text='\t'))
            elif tag == _q('br'):
                runs.append({'br': True})
    para = {'type': 'p', 'runs': clean_runs(runs)}
    para.update(_para_format(p_el))
    return para


def clean_runs(runs):
    """Bỏ run chữ rỗng, gộp run chữ liền nhau cùng định dạng. Đoạn chỉ có khoảng trắng
    không ngắt (&nbsp;, dùng làm dòng trống) thành đoạn không có run nào."""
    if all('text' in r and not r['text'].replace(_NBSP, '').strip() for r in runs):
        return []
    cleaned = []
    for run in runs:
        if 'text' in run and not run['text']:
            continue
        prev = cleaned[-1] if cleaned else None
        if prev and 'text' in prev and 'text' in run and all(prev.get(k) == run.get(k) for k in FORMAT_KEYS):
            prev['text'] += run['text']
        else:
            cleaned.append(dict(run))
    return cleaned


def _table_has_borders(tbl_el):
    """Có viền nếu tblBorders hoặc viền ô có cạnh không phải nil/none. Không khai gì thì
    theo kiểu bảng: tên có 'Grid' (Table Grid) là có viền, còn lại (Normal Table) không."""
    tbl_pr = tbl_el.find(_q('tblPr'))
    declared = []
    for container in tbl_el.iter(_q('tblBorders'), _q('tcBorders')):
        declared += [edge.get(_q('val')) for edge in container]
    if declared:
        return any(val not in _NO_BORDER for val in declared)
    style = tbl_pr.find(_q('tblStyle')) if tbl_pr is not None else None
    return style is not None and 'grid' in (style.get(_q('val')) or '').lower()


def _read_table(tbl_el, keep_fields):
    rows = []
    for tr in tbl_el.findall(_q('tr')):
        row = []
        for tc in tr.findall(_q('tc')):
            span = _int_attr(tc.find('%s/%s' % (_q('tcPr'), _q('gridSpan'))), 'val') or 1
            paras = [_read_paragraph(p, keep_fields) for p in tc.findall(_q('p'))]
            row.append({'span': span, 'paras': paras or [{'type': 'p', 'align': 'left', 'runs': []}]})
        rows.append(row)
    widths = [_int_attr(col, 'w') or 0 for col in tbl_el.findall('%s/%s' % (_q('tblGrid'), _q('gridCol')))]
    return {'type': 'table', 'rows': rows, 'borders': _table_has_borders(tbl_el), 'widths': widths or None}


def _body_elements(container):
    """Con trực tiếp của body, đi xuyên qua content control (w:sdt) mà Word hay bọc ngoài."""
    for child in container:
        if child.tag == _q('sdt'):
            content = child.find(_q('sdtContent'))
            if content is not None:
                yield from _body_elements(content)
        else:
            yield child


def read_docx(docx_bytes, keep_fields=True):
    """Xem docstring đầu module."""
    root = read_xml_parts(docx_bytes)[DOCUMENT_PART]
    body = root.find(_q('body'))
    blocks = []
    for child in _body_elements(body if body is not None else []):
        if child.tag == _q('p'):
            blocks.append(_read_paragraph(child, keep_fields))
        elif child.tag == _q('tbl'):
            blocks.append(_read_table(child, keep_fields))
    return blocks
