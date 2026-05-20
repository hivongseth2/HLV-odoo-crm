# -*- coding: utf-8 -*-
"""
Helper functions để build file Excel xuất phiếu XK.
Tách ra khỏi sale_plan_controller.py để tránh file quá dài.
"""
import io
import logging

_logger = logging.getLogger(__name__)

# ── Nhãn trạng thái ──────────────────────────────────────────────────────────

PICKING_STATE_LABELS = {
    'draft': 'Nháp',
    'waiting': 'Chờ nguyên liệu',
    'confirmed': 'Đã xác nhận',
    'assigned': 'Sẵn sàng xuất',
    'done': 'Hoàn tất',
    'cancel': 'Đã hủy',
}

SO_STATE_LABELS = {
    'draft': 'Nháp',
    'sent': 'Đã gửi báo giá',
    'sale': 'Đơn hàng',
    'done': 'Đã khóa',
    'cancel': 'Đã hủy',
}

DELIVERY_STATUS_LABELS = {
    'pending': 'Chưa giao',
    'unshipped': 'Chưa giao',
    'started': 'Đã bắt đầu',
    'partial': 'Giao 1 phần',
    'full': 'Đã giao đủ',
}


def _get_xlsxwriter():
    try:
        import xlsxwriter
        return xlsxwriter
    except ImportError:
        from odoo.tools.misc import xlsxwriter
        return xlsxwriter


def _format_date_done(date_done, utc_tz, user_tz):
    """Chuyển datetime UTC → chuỗi giờ VN (UTC+7)."""
    if not date_done:
        return ''
    try:
        local_dt = date_done.replace(tzinfo=utc_tz).astimezone(user_tz)
        return local_dt.strftime('%d/%m/%Y %H:%M')
    except Exception:
        return str(date_done)


def _get_tz():
    """Trả về (utc_tz, user_tz). Fallback None nếu pytz không có."""
    try:
        import pytz
        return pytz.UTC, pytz.timezone('Asia/Ho_Chi_Minh')
    except Exception:
        return None, None


# ── Export giản lược (không dòng sản phẩm) ───────────────────────────────────

def build_picking_summary_xlsx(pickings, so_name_map, so_state_map):
    """
    Export tóm tắt phiếu OUT — mỗi hàng = 1 phiếu, không có dòng sản phẩm.

    Columns:
        STT | Mã phiếu XK | Đơn hàng | Trạng thái phiếu | Trạng thái ĐH
        | Kho | Ngày hoàn thành | Tổng tiền trước thuế | Tổng tiền sau thuế

    :param pickings:    recordset stock.picking
    :param so_name_map: {so_id: so_name}
    :param so_state_map:{so_id: so_state_raw}
    :return: bytes nội dung .xlsx
    """
    xlsxwriter = _get_xlsxwriter()
    utc_tz, user_tz = _get_tz()

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    sheet = workbook.add_worksheet('Phiếu XK (tóm tắt)')

    # Formats
    header_fmt = workbook.add_format({
        'bold': True, 'bg_color': '#375623', 'font_color': '#FFFFFF',
        'border': 1, 'align': 'center', 'valign': 'vcenter',
        'font_size': 11, 'text_wrap': True,
    })
    cell_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 10})
    money_fmt = workbook.add_format({
        'border': 1, 'valign': 'vcenter', 'font_size': 10,
        'num_format': '#,##0',
    })
    cancelled_fmt = workbook.add_format({
        'border': 1, 'valign': 'vcenter', 'font_size': 10,
        'font_color': '#C00000', 'bold': True,
    })

    col_headers = [
        ('STT', 5),
        ('Mã phiếu XK', 16),
        ('Đơn hàng', 15),
        ('Trạng thái phiếu', 16),
        ('Trạng thái ĐH', 14),
        ('Kho', 15),
        ('Ngày hoàn thành', 17),
        ('Tổng TT trước thuế', 20),
        ('Tổng TT sau thuế', 20),
    ]

    for col_idx, (name, width) in enumerate(col_headers):
        sheet.write(0, col_idx, name, header_fmt)
        sheet.set_column(col_idx, col_idx, width)
    sheet.freeze_panes(1, 0)

    for row_idx, picking in enumerate(pickings, start=1):
        so_id = picking.sale_id.id if picking.sale_id else False
        so_name = so_name_map.get(so_id) or (picking.sale_id.name if picking.sale_id else '')
        so_state_raw = so_state_map.get(so_id) or (picking.sale_id.state if picking.sale_id else '')
        so_state_label = SO_STATE_LABELS.get(so_state_raw, so_state_raw)
        pick_state_label = PICKING_STATE_LABELS.get(picking.state, picking.state)
        wh_name = (
            picking.location_id.warehouse_id.name
            if picking.location_id and picking.location_id.warehouse_id else ''
        )
        date_done_str = _format_date_done(picking.date_done, utc_tz, user_tz)
        trc_thue = getattr(picking, 'x_studio_tng_tin_trc_thu', 0) or 0
        sau_thue = getattr(picking, 'x_studio_tng_tin_sau_thu', 0) or 0

        _state_fmt = cancelled_fmt if so_state_raw == 'cancel' else cell_fmt

        c = 0
        sheet.write(row_idx, c, row_idx, cell_fmt); c += 1
        sheet.write(row_idx, c, picking.name or '', cell_fmt); c += 1
        sheet.write(row_idx, c, so_name, cell_fmt); c += 1
        sheet.write(row_idx, c, pick_state_label, cell_fmt); c += 1
        sheet.write(row_idx, c, so_state_label, _state_fmt); c += 1
        sheet.write(row_idx, c, wh_name, cell_fmt); c += 1
        sheet.write(row_idx, c, date_done_str, cell_fmt); c += 1
        sheet.write(row_idx, c, trc_thue, money_fmt); c += 1
        sheet.write(row_idx, c, sau_thue, money_fmt)

    workbook.close()
    output.seek(0)
    return output.read()
