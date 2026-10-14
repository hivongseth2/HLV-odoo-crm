# -*- coding: utf-8 -*-
"""Bỏ font nhúng trong file .docx.

Word có tuỳ chọn "Embed fonts in the file": file đề nghị thanh toán 1 trang nặng 11,7 MB chỉ vì mang
theo Times New Roman, Arial… Mẫu hợp đồng chỉ dùng font chuẩn có sẵn trên máy, nên bỏ font nhúng
cho file nhẹ (lưu, tải, gửi) mà hiển thị không đổi.

strip_embedded_fonts(docx_bytes) -> bytes .docx không còn font nhúng. File không nhúng font trả
    nguyên bytes đầu vào. File không phải zip -> ValueError.
"""

import re
import zipfile
from io import BytesIO

_FONT_PART_RE = re.compile(r'^word/fonts/[^/]+$', re.IGNORECASE)
_FONT_RELS = 'word/_rels/fontTable.xml.rels'
# Thẻ trỏ tới font nhúng trong fontTable.xml và cờ "nhúng font" trong settings.xml
_EMBED_TAG_RE = re.compile(r'<w:embed(?:Regular|Bold|Italic|BoldItalic)\b[^>]*/>')
_SETTINGS_FLAG_RE = re.compile(r'<w:(?:embedTrueTypeFonts|embedSystemFonts|saveSubsetFonts)\b[^>]*/>')
_ODTTF_TYPE_RE = re.compile(r'<Default Extension="odttf"[^>]*/>', re.IGNORECASE)


def strip_embedded_fonts(docx_bytes):
    """Xem docstring đầu module."""
    try:
        source = zipfile.ZipFile(BytesIO(docx_bytes))
    except zipfile.BadZipFile as err:
        raise ValueError('File không phải .docx hợp lệ (%s)' % err)
    names = source.namelist()
    if not any(_FONT_PART_RE.match(n) for n in names):
        return docx_bytes
    out = BytesIO()
    with source, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            name = info.filename
            if _FONT_PART_RE.match(name) or name == _FONT_RELS or name.endswith('/'):
                continue
            data = source.read(name)
            if name == 'word/fontTable.xml':
                data = _EMBED_TAG_RE.sub('', data.decode('utf-8')).encode('utf-8')
            elif name == 'word/settings.xml':
                data = _SETTINGS_FLAG_RE.sub('', data.decode('utf-8')).encode('utf-8')
            elif name == '[Content_Types].xml':
                data = _ODTTF_TYPE_RE.sub('', data.decode('utf-8')).encode('utf-8')
            target.writestr(info, data)
    return out.getvalue()
