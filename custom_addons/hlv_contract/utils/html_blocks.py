# -*- coding: utf-8 -*-
"""Chuyển đổi giữa blocks (xem docx_io) và HTML.

HTML dùng cho hai việc: trình soạn mẫu trên Odoo (html field) và bản xem trước /
bản PDF của hợp đồng. Trong HTML, trường biến viết là {{Ten_Bien}} khi soạn mẫu, và
được hiển thị dạng <span class="hlv-var">{{Ten_Bien}}</span> để dễ nhận ra.

blocks_to_html(blocks) -> chuỗi HTML (không có <html>/<body>).
html_to_blocks(html)   -> blocks. Hiểu: p, div, h1-h6, br, strong/b, em/i, u, span,
    ul/ol/li (thêm dấu • ), table/tr/td/th (colspan, <col style="width:..%">, class
    hlv-noborder = bảng không viền, còn lại có viền), căn lề text-align/align, font-size, margin-left,
    text-indent, margin-bottom (pt hoặc px). Thẻ lạ bị bỏ qua nhưng giữ chữ bên trong.
wrap_html_document(fragment) -> trang HTML đầy đủ cho wkhtmltopdf.
Trường hợp biên: {{ ten }} có khoảng trắng vẫn nhận; HTML rỗng -> [].
"""

import re
from xml.sax.saxutils import escape

import lxml.html

from .docx_io import clean_runs

_TOKEN_RE = re.compile(r'\{\{\s*(\w+)\s*\}\}')
_ALIGN_RE = re.compile(r'text-align\s*:\s*(left|center|right|justify)', re.IGNORECASE)
_LENGTH_RE = r'(?:^|;)\s*%s\s*:\s*(-?[\d.]+)\s*(pt|px)'
_WIDTH_PCT_RE = re.compile(r'width\s*:\s*([\d.]+)\s*%')
_BLOCK_TAGS = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'ul', 'ol', 'table', 'blockquote'}
# Dán từ Word vào trình soạn kèm <style>/<meta>/<o:p>...: bỏ cả thẻ lẫn chữ bên trong
_SKIP_TAGS = {'style', 'script', 'meta', 'title', 'head', 'xml', 'link'}
_BOLD_TAGS = {'strong', 'b'}
_ITALIC_TAGS = {'em', 'i'}
_UNDERLINE_TAGS = {'u'}
_ALIGNS = {'left', 'center', 'right', 'justify'}
_PLAIN_FLAGS = {'b': False, 'i': False, 'u': False, 'sz': None}
# Viền bảng đi bằng class (CSS ở wrap_html_document và trang /hop-dong), không inline vào ô,
# để trình soạn mẫu bật/tắt viền cả bảng chỉ bằng đổi class.
_GRID_CLASS = 'hlv-grid'
_NO_BORDER_CLASS = 'hlv-noborder'
_DEFAULT_AFTER_TWIPS = 60
_TWIPS_PER_PT = 20


# ---------- blocks -> HTML ----------

def _text_html(text):
    # Tab giữ dạng ký tự tab trong span white-space:pre để trình duyệt nhảy tới điểm dừng
    # tab kế tiếp, gần giống cách Word canh "Địa chỉ<tab>: ..." thành cột
    return escape(text).replace('\t', '<span style="white-space:pre">\t</span>')


def _run_html(run):
    if run.get('br'):
        return '<br>'
    if run.get('field'):
        return '<span class="hlv-var">{{%s}}</span>' % escape(run['field'])
    html = _text_html(run.get('text') or '')
    if run.get('u'):
        html = '<u>%s</u>' % html
    if run.get('i'):
        html = '<em>%s</em>' % html
    if run.get('b'):
        html = '<strong>%s</strong>' % html
    if run.get('sz'):
        html = '<span style="font-size:%gpt">%s</span>' % (run['sz'] / 2.0, html)
    return html


def _para_html(para):
    body = ''.join(_run_html(r) for r in para.get('runs') or [])
    after = para.get('after')
    styles = [
        'text-align:%s' % (para.get('align') if para.get('align') in _ALIGNS else 'left'),
        'margin-top:0',
        'margin-bottom:%gpt' % ((after if after is not None else _DEFAULT_AFTER_TWIPS) / float(_TWIPS_PER_PT)),
    ]
    if para.get('indent'):
        styles.append('margin-left:%gpt' % (para['indent'] / float(_TWIPS_PER_PT)))
    if para.get('first'):
        styles.append('text-indent:%gpt' % (para['first'] / float(_TWIPS_PER_PT)))
    return '<p style="%s">%s</p>' % (';'.join(styles), body or '&nbsp;')


def _table_html(table):
    borders = table.get('borders', True)
    rows = []
    for row in table.get('rows') or []:
        cells = []
        for cell in row:
            span = int(cell.get('span') or 1)
            colspan = ' colspan="%d"' % span if span > 1 else ''
            inner = ''.join(_para_html(p) for p in cell.get('paras') or [])
            cells.append('<td%s style="padding:2px 5px;vertical-align:top">%s</td>' % (colspan, inner))
        rows.append('<tr>%s</tr>' % ''.join(cells))
    colgroup = ''
    widths = table.get('widths') or []
    if widths and sum(widths):
        total = float(sum(widths))
        colgroup = '<colgroup>%s</colgroup>' % ''.join(
            '<col style="width:%.2f%%">' % (100 * w / total) for w in widths)
    css_class = _GRID_CLASS if borders else _NO_BORDER_CLASS
    return '<table class="%s" style="border-collapse:collapse;width:100%%;table-layout:fixed">%s%s</table>' % (
        css_class, colgroup, ''.join(rows))


def blocks_to_html(blocks):
    """Xem docstring đầu module."""
    parts = []
    for block in blocks:
        if block.get('type') == 'table':
            parts.append(_table_html(block))
        else:
            parts.append(_para_html(block))
    return ''.join(parts)


# ---------- HTML -> blocks ----------

def _style_pt(node, prop):
    """Giá trị pt của thuộc tính CSS inline prop (nhận pt hoặc px), không có -> None."""
    match = re.search(_LENGTH_RE % re.escape(prop), node.get('style') or '', re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    return value * 0.75 if match.group(2).lower() == 'px' else value


def _flags_for(node, flags):
    """Định dạng chữ của node, kế thừa từ flags của cha."""
    tag = node.tag.lower()
    child_flags = dict(flags)
    if tag in _BOLD_TAGS:
        child_flags['b'] = True
    if tag in _ITALIC_TAGS:
        child_flags['i'] = True
    if tag in _UNDERLINE_TAGS:
        child_flags['u'] = True
    size = _style_pt(node, 'font-size')
    if size:
        child_flags['sz'] = int(round(size * 2))
    return child_flags


def _text_to_runs(text, flags, runs):
    pos = 0
    for match in _TOKEN_RE.finditer(text):
        if match.start() > pos:
            runs.append(dict(flags, text=text[pos:match.start()]))
        runs.append({'field': match.group(1)})
        pos = match.end()
    if pos < len(text):
        runs.append(dict(flags, text=text[pos:]))


def _inline_runs(node, flags, runs):
    """Ghi chữ của node (đã áp flags) và các con inline của nó vào runs."""
    if node.text:
        _text_to_runs(node.text, flags, runs)
    for child in node:
        if isinstance(child.tag, str) and child.tag.lower() not in _SKIP_TAGS:
            if child.tag.lower() == 'br':
                runs.append({'br': True})
            else:
                _inline_runs(child, _flags_for(child, flags), runs)
        if child.tail:
            _text_to_runs(child.tail, flags, runs)


def _para_format(node, align=None):
    fmt = {'align': align or 'left'}
    style_align = _ALIGN_RE.search(node.get('style') or '')
    attr_align = (node.get('align') or '').lower()
    if style_align:
        fmt['align'] = style_align.group(1).lower()
    elif attr_align in _ALIGNS:
        fmt['align'] = attr_align
    for prop, key in (('margin-left', 'indent'), ('text-indent', 'first'), ('margin-bottom', 'after')):
        value = _style_pt(node, prop)
        if value is not None:
            fmt[key] = int(round(value * _TWIPS_PER_PT))
    return fmt


def _para_from(node, prefix=''):
    runs = [{'text': prefix}] if prefix else []
    _inline_runs(node, _flags_for(node, _PLAIN_FLAGS), runs)
    para = {'type': 'p', 'runs': clean_runs(runs)}
    para.update(_para_format(node))
    return para


def _has_block_children(node):
    return any(isinstance(c.tag, str) and c.tag.lower() in _BLOCK_TAGS for c in node)


def _table_from(node):
    rows = []
    for tr in node.iter('tr'):
        row = []
        for cell in tr:
            if not isinstance(cell.tag, str) or cell.tag.lower() not in ('td', 'th'):
                continue
            span = int(cell.get('colspan') or 1)
            paras = _emit_blocks(cell, align=_para_format(cell)['align'])
            row.append({'span': span, 'paras': paras or [{'type': 'p', 'align': 'left', 'runs': []}]})
        rows.append(row)
    widths = []
    for col in node.iter('col'):
        match = _WIDTH_PCT_RE.search(col.get('style') or '')
        widths.append(float(match.group(1)) if match else 0)
    classes = (node.get('class') or '').split()
    return {'type': 'table', 'rows': rows, 'borders': _NO_BORDER_CLASS not in classes,
            'widths': widths if widths and all(widths) else None}


def _emit_blocks(node, align=None):
    """Biến con của node thành list blocks. Chữ/thẻ inline liền nhau gom thành một đoạn;
    thẻ block (p, div, h*, li, table) thì ngắt đoạn. align: căn lề mặc định của đoạn gom."""
    out = []
    pending = []
    default_align = align or _para_format(node)['align']

    def flush():
        if pending:
            out.append({'type': 'p', 'align': default_align, 'runs': clean_runs(pending)})
            del pending[:]

    if node.text:
        _text_to_runs(node.text, _PLAIN_FLAGS, pending)
    for child in node:
        if isinstance(child.tag, str) and child.tag.lower() not in _SKIP_TAGS:
            tag = child.tag.lower()
            if tag == 'br':
                pending.append({'br': True})
            elif tag == 'table':
                flush()
                out.append(_table_from(child))
            elif tag in ('ul', 'ol'):
                flush()
                for li in child:
                    if isinstance(li.tag, str) and li.tag.lower() == 'li':
                        out.append(_para_from(li, prefix='• '))
            elif tag in _BLOCK_TAGS:
                flush()
                if _has_block_children(child):
                    out += _emit_blocks(child)
                else:
                    out.append(_para_from(child))
            else:
                _inline_runs(child, _flags_for(child, _PLAIN_FLAGS), pending)
        if child.tail:
            _text_to_runs(child.tail, _PLAIN_FLAGS, pending)
    flush()
    return out


def html_to_blocks(html):
    """Xem docstring đầu module."""
    if not html or not html.strip():
        return []
    root = lxml.html.fromstring('<div>%s</div>' % html)
    return _emit_blocks(root)


# Font in hợp đồng: Tinos (OFL, đo chữ y hệt Times New Roman, đủ tiếng Việt) đóng gói trong
# static/fonts. Server Linux không có Times New Roman; để wkhtmltopdf tự chọn font thay thế
# thì dòng chữ in hoa đậm bị rơi dấu (CỘNG HOÀ -> CỌNG HOA).
FONT_FAMILY = '"Tinos", "Times New Roman", "Liberation Serif", serif'
_FONT_FILES = (('Regular', 'normal', 'normal'), ('Bold', 'bold', 'normal'),
               ('Italic', 'normal', 'italic'), ('BoldItalic', 'bold', 'italic'))
_PAGE_CSS = (
    'body { font-family: %s; font-size: 13pt; line-height: 1.3; color: #000; }'
    'table { border-collapse: collapse; }'
    'table.hlv-grid td { border: 1px solid #000; }'
    'tr { page-break-inside: avoid; }'
) % FONT_FAMILY


def font_face_css(base_url):
    """@font-face cho 4 kiểu Tinos. base_url: gốc web Odoo mà wkhtmltopdf truy cập được
    (ví dụ 'http://localhost:8069'); '' -> đường dẫn tương đối (dùng trong trình duyệt)."""
    return ''.join(
        '@font-face { font-family: "Tinos"; src: url("%s/hlv_contract/static/fonts/Tinos-%s.ttf") '
        'format("truetype"); font-weight: %s; font-style: %s; }' % ((base_url or '').rstrip('/'), name, weight, style)
        for name, weight, style in _FONT_FILES)


def wrap_html_document(fragment, base_url=''):
    """Bọc phần thân hợp đồng thành một trang HTML đầy đủ cho wkhtmltopdf. Mỗi hợp đồng
    là một tài liệu riêng nên khi gộp PDF sẽ bắt đầu trên trang mới. base_url: xem font_face_css."""
    return ('<!DOCTYPE html><html><head><meta charset="utf-8"><style>%s%s</style></head>'
            '<body>%s</body></html>') % (font_face_css(base_url), _PAGE_CSS, fragment)
