# -*- coding: utf-8 -*-
import io
from datetime import datetime


def _get_xlsxwriter():
    try:
        import xlsxwriter
        return xlsxwriter
    except ImportError:
        from odoo.tools.misc import xlsxwriter
        return xlsxwriter


def _display_date(date_value):
    try:
        return datetime.strptime(date_value or '', '%Y-%m-%d').strftime('%d/%m/%Y')
    except Exception:
        return date_value or ''


def _display_date_range(date_from, date_to=None):
    date_from = date_from or ''
    date_to = date_to or date_from
    if not date_to or date_to == date_from:
        return _display_date(date_from)
    return '%s - %s' % (_display_date(date_from), _display_date(date_to))


def _write_group_cell(sheet, first_row, last_row, col, value, fmt):
    if first_row == last_row:
        sheet.write(first_row, col, value, fmt)
    else:
        sheet.merge_range(first_row, col, last_row, col, value, fmt)


def build_sale_plan_messages_xlsx(groups, date_from, date_to=None):
    xlsxwriter = _get_xlsxwriter()
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    sheet = workbook.add_worksheet('Tin nhắn')

    title_fmt = workbook.add_format({
        'bold': True, 'font_size': 14, 'font_color': '#FFFFFF',
        'bg_color': '#1F4E78', 'align': 'center', 'valign': 'vcenter',
    })
    info_fmt = workbook.add_format({
        'italic': True, 'font_color': '#4B5563', 'valign': 'vcenter',
    })
    header_fmt = workbook.add_format({
        'bold': True, 'bg_color': '#D9EAF7', 'font_color': '#0F172A',
        'border': 1, 'align': 'center', 'valign': 'vcenter',
        'font_size': 10, 'text_wrap': True,
    })
    order_fmt = workbook.add_format({
        'border': 1, 'valign': 'vcenter', 'align': 'center',
        'font_size': 10, 'bold': True, 'text_wrap': True,
        'bg_color': '#F8FAFC',
    })
    cell_fmt = workbook.add_format({
        'border': 1, 'valign': 'top', 'font_size': 10, 'text_wrap': True,
    })
    center_fmt = workbook.add_format({
        'border': 1, 'valign': 'top', 'align': 'center',
        'font_size': 10, 'text_wrap': True,
    })
    body_fmt = workbook.add_format({
        'border': 1, 'valign': 'top', 'font_size': 10, 'text_wrap': True,
    })

    headers = [
        ('STT đơn', 8),
        ('Đơn hàng', 16),
        ('Khách hàng', 28),
        ('Kho', 16),
        ('STT tin', 8),
        ('Thời gian', 18),
        ('Nguồn', 16),
        ('Người gửi', 22),
        ('Nội dung', 70),
        ('File đính kèm', 28),
    ]

    total_messages = sum(len(group.get('messages') or []) for group in groups)
    sheet.merge_range(0, 0, 0, len(headers) - 1, 'Tin nhắn Sale - Thủ kho %s' % _display_date_range(date_from, date_to), title_fmt)
    sheet.merge_range(
        1, 0, 1, len(headers) - 1,
        'Tổng đơn: %s | Tổng tin nhắn: %s' % (len(groups), total_messages),
        info_fmt,
    )

    header_row = 3
    for col, (label, width) in enumerate(headers):
        sheet.write(header_row, col, label, header_fmt)
        sheet.set_column(col, col, width)
    sheet.freeze_panes(header_row + 1, 0)
    sheet.autofilter(header_row, 0, header_row, len(headers) - 1)

    row = header_row + 1
    if not groups:
        sheet.merge_range(row, 0, row, len(headers) - 1, 'Không có tin nhắn người dùng trong ngày đã chọn.', cell_fmt)
        workbook.close()
        output.seek(0)
        return output.read()

    for order_idx, group in enumerate(groups, start=1):
        messages = group.get('messages') or []
        if not messages:
            continue
        first_row = row
        for msg_idx, msg in enumerate(messages, start=1):
            sheet.write(row, 4, msg_idx, center_fmt)
            sheet.write(row, 5, msg.get('date', ''), cell_fmt)
            sheet.write(row, 6, msg.get('origin', ''), cell_fmt)
            sheet.write(row, 7, msg.get('author', ''), cell_fmt)
            sheet.write(row, 8, msg.get('body', ''), body_fmt)
            sheet.write(row, 9, msg.get('attachments', ''), cell_fmt)
            body_lines = max(1, len((msg.get('body') or '').splitlines()))
            sheet.set_row(row, min(120, 18 + body_lines * 13))
            row += 1
        last_row = row - 1
        _write_group_cell(sheet, first_row, last_row, 0, order_idx, order_fmt)
        _write_group_cell(sheet, first_row, last_row, 1, group.get('order_name', ''), order_fmt)
        _write_group_cell(sheet, first_row, last_row, 2, group.get('customer_name', ''), order_fmt)
        _write_group_cell(sheet, first_row, last_row, 3, group.get('warehouse_name', ''), order_fmt)

    workbook.close()
    output.seek(0)
    return output.read()
