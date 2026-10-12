# -*- coding: utf-8 -*-
"""Xuất / in hàng loạt hợp đồng: Word (một file hoặc gói zip), PDF gộp một file, Excel
(mỗi mẫu một sheet).

PDF dùng wkhtmltopdf mà Odoo đã có sẵn để in báo cáo, nên không cần cài thêm gì. File trả
thẳng về trình duyệt, không lưu đính kèm (xuất nhiều lần không làm phình filestore).
"""

import re
import zipfile
from io import BytesIO

from odoo import fields

from ..models.contract import STATES
from ..utils.contract_excel import build_workbook
from ..utils.contract_vars import LINE_FIELDS, TOTAL_VARIABLES
from ..utils.html_blocks import wrap_html_document

FORMATS = {
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'pdf': 'application/pdf',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'zip': 'application/zip',
}
_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|]+')
_EXCEL_KIND = {'date': 'date', 'money': 'money', 'number': 'number'}


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
    # Report tạm trong bộ nhớ (new, không lưu DB) chỉ để _run_wkhtmltopdf lấy khổ giấy hợp
    # đồng thay vì khổ mặc định của công ty (lề trái 0, lề trên 52 mm); nội dung không qua QWeb
    paperformat = contracts.env.ref('hlv_contract.paperformat_hlv_contract')
    report = contracts.env['ir.actions.report'].new({'paperformat_id': paperformat.id})
    # Font tải qua cùng địa chỉ Odoo dùng cho CSS báo cáo (report.url) — wkhtmltopdf chạy với
    # --disable-local-file-access nên không đọc file trên đĩa được
    base_url = report._get_report_url()
    bodies = [wrap_html_document(contract._render_html_fragment(), base_url) for contract in contracts]
    pdf = report._run_wkhtmltopdf(bodies)
    name = safe_filename(contracts.name) if len(contracts) == 1 else 'hop-dong-%d-ban' % len(contracts)
    return '%s.pdf' % name, pdf, FORMATS['pdf']


def _excel_value(var_type, raw):
    """Giá trị biến -> kiểu Excel: ngày -> date, số -> float; chuỗi không đọc được giữ nguyên."""
    if raw in (None, ''):
        return None
    try:
        if var_type == 'date':
            return fields.Date.to_date(raw)
        if var_type in ('money', 'number'):
            return float(raw)
    except ValueError:
        return raw
    return raw


def _template_sheet(template, contracts):
    """Một sheet cho các hợp đồng cùng mẫu: số HĐ, ngày ký, trạng thái, các biến nhập của mẫu,
    rồi dòng hàng trải ngang (Ten_Hang_1, DVT_1...) và tổng tiền nếu mẫu có bảng hàng."""
    columns = [('So_Hop_Dong', 'text'), ('Ngay_Ky', 'date'), ('Trang_Thai', 'text')]
    columns += [(var.name, _EXCEL_KIND.get(var.var_type, 'text')) for var in template.variable_ids]
    if template.has_lines:
        max_lines = max([1] + [len(c.line_ids) for c in contracts])
        for index in range(1, max_lines + 1):
            columns += [('Ten_Hang_%d' % index, 'text'), ('DVT_%d' % index, 'text'),
                        ('So_Luong_%d' % index, 'number'), ('Don_Gia_%d' % index, 'money'),
                        ('Thanh_Tien_%d' % index, 'money')]
        columns += [(name, 'number' if name == 'Thue_Suat_VAT' else 'text' if name.endswith('Chu') else 'money')
                    for name in TOTAL_VARIABLES]
    columns.append(('Ghi_Chu', 'text'))
    types = {var.name: var.var_type for var in template.variable_ids}
    states = dict(STATES)
    rows = []
    for contract in contracts:
        values = contract.variable_values or {}
        row = {
            'So_Hop_Dong': contract.name,
            'Ngay_Ky': contract.contract_date,
            'Trang_Thai': states.get(contract.state),
            'Ghi_Chu': contract.note,
            'Tong_Tien_Hang': contract.amount_untaxed,
            'Thue_Suat_VAT': contract.vat_rate,
            'Tien_Thue_VAT': contract.amount_vat,
            'Tong_Gia_Tri_HD': contract.amount_total,
            'Tong_Gia_Tri_Bang_Chu': contract.amount_words,
        }
        row.update({name: _excel_value(var_type, values.get(name)) for name, var_type in types.items()})
        for index, line in enumerate(contract.line_ids, start=1):
            row.update(dict(zip(['%s_%d' % (f, index) for f in LINE_FIELDS],
                                [line.product_name, line.uom, line.quantity, line.price_unit, line.subtotal])))
        rows.append(row)
    return {'title': template.name, 'columns': columns, 'rows': rows}


def _export_xlsx(contracts):
    sheets = [_template_sheet(template, contracts.filtered(lambda c, t=template: c.template_id == t))
              for template in contracts.mapped('template_id')]
    return 'danh-sach-hop-dong.xlsx', build_workbook(sheets), FORMATS['xlsx']


_EXPORTERS = {'docx': _export_docx, 'pdf': _export_pdf, 'xlsx': _export_xlsx}


def export_contracts(contracts, fmt):
    """contracts: recordset hlv.contract (đã kiểm quyền đọc); fmt: 'docx' | 'pdf' | 'xlsx'.
    Trả (tên file, bytes, mimetype). fmt lạ -> ValueError."""
    if fmt not in _EXPORTERS:
        raise ValueError('Định dạng không hỗ trợ: %s' % fmt)
    return _EXPORTERS[fmt](contracts)
