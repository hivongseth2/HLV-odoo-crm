"""Nguồn hàng của một đơn bán: các đơn MUA phải về thì đơn bán mới giao được.

Quy ước nối của công ty: ``purchase.order.origin`` = tên đơn bán. Không có khoá ngoại nào
giữa hai bên — chỉ có chuỗi đó — nên mọi chỗ cần biết "đơn này chờ hàng gì" đều phải đi qua
đây, để luật so chuỗi chỉ nằm một nơi.
"""

import re

from .serialize import iso_date, iso_datetime, partner_block

# `origin` có thể gộp nhiều chứng từ: "DH001, DH002" hoặc "DH001 / DH002".
_ORIGIN_SPLIT_RE = re.compile(r'[,;/\s]+')

# Trạng thái đơn mua còn có thể mang hàng về. Nháp/chờ duyệt vẫn tính: với AI lập kế
# hoạch, một đơn mua chưa duyệt nghĩa là hàng còn xa chứ không phải là không có gì.
_LIVE_STATES = ('draft', 'sent', 'to approve', 'purchase', 'done')


def origin_tokens(origin):
    """Tách chuỗi ``origin`` thành tập tên chứng từ. Rỗng/None trả tập rỗng. Hàm thuần."""
    return {token for token in _ORIGIN_SPLIT_RE.split(origin or '') if token}


def purchases_by_order_name(env, order_names):
    """dict {tên đơn bán: recordset đơn mua} cho một loạt đơn bán — MỘT truy vấn.

    Tìm bằng ``ilike`` rồi lọc lại theo token nguyên vẹn: ``ilike 'S0768'`` sẽ khớp nhầm
    cả ``S07687``, và gắn nhầm đơn mua của khách khác vào là loại lỗi AI không tự phát
    hiện được.
    """
    names = [name for name in order_names if name]
    result = {name: env['purchase.order'] for name in names}
    if not names:
        return result
    domain = [('state', 'in', _LIVE_STATES)] + ['|'] * (len(names) - 1) + [
        ('origin', 'ilike', name) for name in names
    ]
    wanted = set(names)
    for purchase in env['purchase.order'].search(domain):
        for token in origin_tokens(purchase.origin) & wanted:
            result[token] |= purchase
    return result


def purchase_block(purchase):
    """Một đơn mua ở dạng dict: ai bán, về kho nào, dự kiến về khi nào, đã về bao nhiêu."""
    ordered = sum(purchase.order_line.mapped('product_qty'))
    received = sum(purchase.order_line.mapped('qty_received'))
    return {
        'id': purchase.id,
        'name': purchase.name,
        'origin': purchase.origin or None,
        'vendor': partner_block(purchase.partner_id),
        'state': purchase.state,
        'receipt_status': purchase_receipt_status(purchase, ordered, received),
        'order_date': iso_datetime(purchase.date_order),
        'expected_arrival': iso_datetime(purchase.date_planned),
        'received_date': iso_datetime(purchase.effective_date) if 'effective_date' in purchase._fields else None,
        'warehouse': purchase.picking_type_id.warehouse_id.name or None,
        'warehouse_id': purchase.picking_type_id.warehouse_id.id or None,
        'qty_ordered': ordered,
        'qty_received': received,
        'amount_total': purchase.amount_total,
        'lines': [{
            'product': line.product_id.display_name,
            'qty_ordered': line.product_qty,
            'qty_received': line.qty_received,
            'expected_arrival': iso_datetime(line.date_planned),
        } for line in purchase.order_line if line.product_id],
    }


def purchase_receipt_status(purchase, ordered=None, received=None):
    """Tình trạng về hàng của một đơn mua: ``not_confirmed`` / ``pending`` / ``partial`` /
    ``full``.

    Tự tính từ số lượng thay vì đọc ``receipt_status`` của Odoo: field đó chỉ có nghĩa khi
    đơn đã xác nhận, còn ở đây cần phân biệt thêm "chưa xác nhận" — hàng còn xa nhất.
    """
    if purchase.state in ('draft', 'sent', 'to approve'):
        return 'not_confirmed'
    if ordered is None:
        ordered = sum(purchase.order_line.mapped('product_qty'))
        received = sum(purchase.order_line.mapped('qty_received'))
    if received <= 0:
        return 'pending'
    return 'full' if received >= ordered else 'partial'


def supply_summary(purchases):
    """Tóm tắt nguồn hàng của MỘT đơn bán từ các đơn mua gắn với nó.

    ``supply_state``:
    - ``no_purchase``  — không có đơn mua nào: hàng lấy từ tồn kho, không phải chờ ai.
    - ``waiting``      — còn đơn mua chưa về đủ: ĐƠN BÁN CHƯA GIAO ĐƯỢC TRỌN.
    - ``arrived``      — mọi đơn mua đã về đủ.

    ``expected_arrival`` là ngày về MUỘN NHẤT trong các đơn mua còn chờ — đơn bán chỉ chạy
    được khi món cuối cùng về tới.
    """
    if not purchases:
        return {
            'supply_state': 'no_purchase', 'purchase_count': 0,
            'waiting_purchases': [], 'expected_arrival': None, 'expected_arrival_date': None,
        }
    waiting = purchases.filtered(lambda p: purchase_receipt_status(p) != 'full')
    # Lọc ngày rỗng trước khi lấy max: đơn mua nháp hay chưa có ngày dự kiến, mà so False
    # với datetime là ném TypeError.
    latest = max((moment for moment in waiting.mapped('date_planned') if moment), default=None)
    return {
        'supply_state': 'waiting' if waiting else 'arrived',
        'purchase_count': len(purchases),
        'waiting_purchases': waiting.mapped('name'),
        'expected_arrival': iso_datetime(latest),
        'expected_arrival_date': iso_date(latest.date()) if latest else None,
    }
