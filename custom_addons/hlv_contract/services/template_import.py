# -*- coding: utf-8 -*-
"""Đổi file người dùng tải lên (.docx / .doc) thành giá trị ghi vào hlv.contract.template.

.docx: giữ nguyên file (mẫu Word, điền MERGEFIELD) hoặc mở trong trình soạn của trang.
.doc : chỉ đọc được chữ và trường trộn, mất định dạng nên luôn mở trong trình soạn để
       người dùng chỉnh lại trước khi dùng.
"""

import base64
import os

from odoo.exceptions import UserError

from ..utils import docx_io, html_blocks
from ..utils.doc_binary import read_doc_blocks


def template_vals_from_upload(filename, data, keep_word_file):
    """filename: tên file gốc; data: bytes; keep_word_file: True = giữ nguyên file .docx.
    Trả dict vals (source, docx_file/docx_filename hoặc body_html, note).
    Đuôi khác .doc/.docx hoặc file hỏng -> UserError."""
    ext = os.path.splitext(filename or '')[1].lower()
    if ext == '.docx':
        try:
            blocks = docx_io.read_docx(data, keep_fields=True)
        except ValueError as err:
            raise UserError('File .docx không đọc được: %s' % err)
        if keep_word_file:
            return {'source': 'docx', 'docx_file': base64.b64encode(data), 'docx_filename': filename}
        return {'source': 'builder', 'body_html': html_blocks.blocks_to_html(blocks)}
    if ext == '.doc':
        try:
            blocks = read_doc_blocks(data)
        except (ValueError, IndexError) as err:
            raise UserError('File .doc không đọc được: %s. Thử mở bằng Word và lưu lại dạng .docx.' % err)
        return {
            'source': 'builder',
            'body_html': html_blocks.blocks_to_html(blocks),
            'note': 'Import từ %s: định dạng chữ (đậm, căn lề) và bảng cần kiểm tra lại.' % filename,
        }
    raise UserError('Chỉ hỗ trợ file .doc hoặc .docx.')
