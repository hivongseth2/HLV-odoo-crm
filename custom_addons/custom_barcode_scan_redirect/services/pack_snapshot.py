# -*- coding: utf-8 -*-
"""Chụp và so nội dung phiếu PACK giữa lúc màn hình đóng gói mở ra và hiện tại.

Phiếu PACK có thể đổi ngay trong lúc đang đóng: với giao 3 bước, Odoo 18 tạo dòng
PACK bằng luật đẩy khi PICK xong và nhét vào phiếu PACK cùng đơn còn dở (chưa in),
gộp luôn vào dòng cùng sản phẩm. PICK bổ sung buổi chiều vì thế làm số yêu cầu của
phiếu đang đóng tăng ngay trên dòng cũ, trong khi màn hình vẫn hiện số lúc tải trang.
"""

# Số yêu cầu là float; lệch dưới ngưỡng này là sai số làm tròn, không phải thay đổi thật.
DEMAND_TOLERANCE = 0.0001


def pack_snapshot(rows):
    """Chụp các dòng phiếu thành dạng gửi được qua JSON.

    Nhận: iterable các bộ (move_id, tên sản phẩm, số yêu cầu).
    Trả: list dict {'move_id': int, 'product': str, 'demand': float} sắp theo move_id.
    Biên: rows rỗng → []; tên None → ''; số yêu cầu None → 0.0.
    """
    return sorted(
        (
            {'move_id': int(move_id), 'product': product or '', 'demand': float(demand or 0.0)}
            for move_id, product, demand in rows
        ),
        key=lambda row: row['move_id'],
    )


def _index_by_move(snapshot):
    """Bản chụp → dict move_id → {'product', 'demand'}; phần tử hỏng bị bỏ qua."""
    index = {}
    for row in snapshot:
        try:
            index[int(row['move_id'])] = {
                'product': str(row.get('product') or ''),
                'demand': float(row.get('demand') or 0.0),
            }
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    return index


def diff_pack_snapshot(old, new):
    """Liệt kê những dòng khác nhau giữa bản chụp cũ (trình duyệt giữ) và bản chụp mới.

    Nhận: old, new — list như pack_snapshot trả. old đi từ trình duyệt về nên không tin
    kiểu: không phải list → không có gì để so, trả []; phần tử hỏng bị bỏ qua.
    Trả: list dict {'product': str, 'old': float | None, 'new': float | None} sắp theo
    move_id. 'old' None = dòng mới xuất hiện, 'new' None = dòng đã rời phiếu.
    Không lệch → [].
    """
    if not isinstance(old, list) or not isinstance(new, list):
        return []
    before = _index_by_move(old)
    after = _index_by_move(new)
    changes = []
    for move_id in sorted(before.keys() | after.keys()):
        was, now = before.get(move_id), after.get(move_id)
        if was and now and abs(was['demand'] - now['demand']) <= DEMAND_TOLERANCE:
            continue
        changes.append({
            'product': (now or was)['product'],
            'old': was['demand'] if was else None,
            'new': now['demand'] if now else None,
        })
    return changes
