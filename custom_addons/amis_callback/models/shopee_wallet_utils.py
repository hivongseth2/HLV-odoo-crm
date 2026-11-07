# -*- coding: utf-8 -*-
"""Hàm thuần đọc bảng "Chi tiết giao dịch" của báo cáo Ví Shopee.

File ví liệt kê mọi loại giao dịch (doanh thu đơn, hoàn tiền, phí, rút tiền,
điều chỉnh...). Phiếu bán hàng MISA chỉ được lập từ dòng doanh thu đơn hàng
thực thu, nên phải lọc trước khi lấy mã đơn.
"""

# Tiêu đề cột trong file ví và vị trí dự phòng (0-based) nếu không dò được tên.
_COLUMN_KEYS = {
    'transaction_type': ('loại giao dịch', 1),   # cột B
    'order_code': ('mã đơn hàng', 3),            # cột D
    'cash_flow': ('dòng tiền', 4),               # cột E
    'amount': ('số tiền', 5),                    # cột F
}

ORDER_REVENUE_LABEL = 'doanh thu đơn hàng'
CASH_IN_LABEL = 'tiền vào'


def _norm(value):
    """Chuỗi so sánh được: None → '', bỏ khoảng trắng thừa, về chữ thường."""
    return ' '.join(str(value or '').split()).lower()


def wallet_column_indexes(header_row):
    """Dò vị trí các cột cần dùng trong dòng tiêu đề của bảng giao dịch.

    Nhận: list ô của dòng tiêu đề (có thể None, có thể thiếu ô).
    Trả: dict key → index 0-based cho 'transaction_type', 'order_code',
    'cash_flow', 'amount'. Cột nào không thấy tên thì lấy vị trí mặc định
    theo mẫu file ví (B/D/E/F). header_row rỗng → toàn bộ là mặc định.
    """
    cells = [_norm(c) for c in (header_row or [])]
    indexes = {}
    for key, (label, default_idx) in _COLUMN_KEYS.items():
        found = default_idx
        for idx, cell in enumerate(cells):
            if cell == label:
                found = idx
                break
        indexes[key] = found
    return indexes


def parse_amount(value):
    """Đọc ô "Số tiền" ra float.

    Nhận: số, hoặc chuỗi kiểu '2.153.620' / '2,153,620' / '-113.479' / ''.
    Trả: float; ô rỗng hoặc không đọc được trả 0.0 (coi như không có tiền vào).
    """
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(' ', '')
    if not text:
        return 0.0
    # Dấu phân cách nghìn có thể là '.' hoặc ','; phần thập phân của file ví
    # luôn là .00 nếu có, nên chỉ giữ dấu cuối cùng khi nó đứng trước 1-2 số.
    neg = text.startswith('-')
    text = text.lstrip('+-')
    sep = max(text.rfind('.'), text.rfind(','))
    if sep != -1 and len(text) - sep - 1 in (1, 2):
        whole, frac = text[:sep], text[sep + 1:]
    else:
        whole, frac = text, ''
    digits = ''.join(ch for ch in whole if ch.isdigit())
    if not digits and not frac:
        return 0.0
    try:
        amount = float('%s.%s' % (digits or '0', frac or '0'))
    except ValueError:
        return 0.0
    return -amount if neg else amount


def is_order_revenue_row(row, indexes):
    """Dòng này có phải doanh thu đơn hàng thực thu không?

    Nhận: list ô của một dòng dữ liệu và dict chỉ số từ wallet_column_indexes.
    Trả: True khi Loại giao dịch là "Doanh thu đơn hàng", Dòng tiền là
    "Tiền vào" và Số tiền > 0. Dòng thiếu ô, dòng trống, hoàn tiền, phí,
    rút tiền đều trả False.
    """
    row = list(row or [])

    def cell(key):
        idx = indexes.get(key)
        return row[idx] if idx is not None and idx < len(row) else None

    if _norm(cell('transaction_type')) != ORDER_REVENUE_LABEL:
        return False
    if _norm(cell('cash_flow')) != CASH_IN_LABEL:
        return False
    return parse_amount(cell('amount')) > 0
