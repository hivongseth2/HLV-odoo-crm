# -*- coding: utf-8 -*-
"""Xuất danh sách hợp đồng ra .xlsx theo đúng cột của form Excel cũ (HDMB/HDNT).

Cột dùng tên biến như form cũ để người quen form đọc được ngay. Giá trị là số thật
(không phải chuỗi đã format) để Excel tính tiếp được.

build_contract_xlsx(rows) -> bytes. rows: list dict khoá theo CONTRACT_XLSX_COLUMNS và
cột dòng hàng Ten_Hang_1..; khoá thiếu -> ô trống. Cột dòng hàng có tối thiểu 10 dòng như
form cũ, nhiều hơn nếu có hợp đồng dài hơn. Trả về file một sheet, dòng 1 là tiêu đề.
Trường hợp biên: rows rỗng vẫn ra file có dòng tiêu đề.
"""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from .contract_vars import LINE_COUNT, LINE_FIELDS, LINE_VARIABLE_RE

CONTRACT_XLSX_COLUMNS = (
    ['So_Hop_Dong', 'Loai_Hop_Dong', 'Ngay_Ky', 'Ngay_Het_Han',
     'Ten_Ben_Mua', 'Dia_Chi_Ben_Mua', 'Ma_So_Thue_Ben_Mua', 'Dien_Thoai_Ben_Mua', 'Fax_Ben_Mua',
     'Nguoi_Dai_Dien_Ben_Mua', 'Chuc_Vu_Ben_Mua', 'Mat_Hang_Chinh', 'Thoi_Gian_Giao_Hang',
     'Dia_Diem_Giao_Hang', 'Dieu_Kien_Thanh_Toan', 'Toa_An_Giai_Quyet',
     'Tong_Tien_Hang', 'Thue_Suat_VAT', 'Tien_Thue_VAT', 'Tong_Gia_Tri_HD', 'Tong_Gia_Tri_Bang_Chu',
     'Trang_Thai', 'Ghi_Chu']
)

_DATE_COLUMNS = {'Ngay_Ky', 'Ngay_Het_Han'}
_MONEY_COLUMNS = {'Tong_Tien_Hang', 'Tien_Thue_VAT', 'Tong_Gia_Tri_HD'}
_HEADER_FILL = PatternFill('solid', fgColor='1F4E78')


def build_contract_xlsx(rows):
    """Xem docstring đầu module."""
    max_lines = max([LINE_COUNT] + [int(m.group(2)) for row in rows for key in row
                                    for m in [LINE_VARIABLE_RE.match(key)] if m])
    columns = CONTRACT_XLSX_COLUMNS + ['%s_%d' % (f, i) for i in range(1, max_lines + 1) for f in LINE_FIELDS]
    wb = Workbook()
    ws = wb.active
    ws.title = 'HopDong'
    ws.append(columns)
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = _HEADER_FILL
    for row in rows:
        ws.append([row.get(col) for col in columns])
    for idx, col in enumerate(columns, start=1):
        ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = 18
        number_format = None
        if col in _DATE_COLUMNS:
            number_format = 'dd/mm/yyyy'
        elif col in _MONEY_COLUMNS or col.startswith(('Don_Gia_', 'Thanh_Tien_')):
            number_format = '#,##0'
        if number_format:
            for cell in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
                cell[0].number_format = number_format
    ws.freeze_panes = 'B2'
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
