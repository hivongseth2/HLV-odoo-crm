# -*- coding: utf-8 -*-
"""Xuất / in hàng loạt hợp đồng: Word (một file hoặc gói zip), PDF gộp một file, Excel.

PDF dùng wkhtmltopdf mà Odoo đã có sẵn để in báo cáo, nên không cần cài thêm gì. File trả
thẳng về trình duyệt, không lưu đính kèm (xuất nhiều lần không làm phình filestore).
"""

import re
import zipfile
from io import BytesIO

from ..utils.contract_excel import build_contract_xlsx
from ..utils.html_blocks import wrap_html_document

FORMATS = {
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'pdf': 'application/pdf',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'zip': 'application/zip',
}
_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|]+')


def safe_filename(name):
    """Số hợp đồng có '/', không dùng làm tên file được: 'HĐMB-001/2026' -> 'HĐMB-001-2026'.
    Rỗng -> 'hop-dong'."""
    return _UNSAFE_FILENAME.sub('-', name or '').strip() or 'hop-dong'


def _export_docx(contracts):
    if len(contracts) == 1:
        return '%s.docx' % safe_filename(contracts.name), contracts._render_docx_bytes(), FORMATS['docx']
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for contract in contracts:
            zf.writestr('%s.docx' % safe_filename(contract.name), contract._render_docx_bytes())
    return 'hop-dong-%d-file.zip' % len(contracts), buffer.getvalue(), FORMATS['zip']


def _export_pdf(contracts):
    bodies = [wrap_html_document(contract._render_html_fragment()) for contract in contracts]
    # Report tạm trong bộ nhớ (new, không lưu DB) chỉ để _run_wkhtmltopdf lấy khổ giấy hợp
    # đồng thay vì khổ mặc định của công ty (lề trái 0, lề trên 52 mm); nội dung không qua QWeb
    paperformat = contracts.env.ref('hlv_contract.paperformat_hlv_contract')
    report = contracts.env['ir.actions.report'].new({'paperformat_id': paperformat.id})
    pdf = report._run_wkhtmltopdf(bodies)
    name = safe_filename(contracts.name) if len(contracts) == 1 else 'hop-dong-%d-ban' % len(contracts)
    return '%s.pdf' % name, pdf, FORMATS['pdf']


def _export_xlsx(contracts):
    content = build_contract_xlsx([contract._excel_row() for contract in contracts])
    return 'danh-sach-hop-dong.xlsx', content, FORMATS['xlsx']


_EXPORTERS = {'docx': _export_docx, 'pdf': _export_pdf, 'xlsx': _export_xlsx}


def export_contracts(contracts, fmt):
    """contracts: recordset hlv.contract (đã kiểm quyền đọc); fmt: 'docx' | 'pdf' | 'xlsx'.
    Trả (tên file, bytes, mimetype). fmt lạ -> ValueError."""
    if fmt not in _EXPORTERS:
        raise ValueError('Định dạng không hỗ trợ: %s' % fmt)
    return _EXPORTERS[fmt](contracts)
