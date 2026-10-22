# -*- coding: utf-8 -*-
"""Áp voucher Loyalty vào đơn Mini App và lấy về lý do khi không áp được.

Hai đường đặt hàng trước đây bắt lỗi áp mã rồi vẫn tạo đơn — khách thấy "đã áp
dụng mã" mà đơn không có giảm giá/quà. Mọi quy tắc voucher nằm ở
sale.order.action_apply_loyalty_voucher (hlv_loyalty); ở đây chỉ gọi nó và trả
lý do lỗi, không tự kiểm lại quy tắc nào.
"""
import logging

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

GENERIC_ERROR = 'Không áp dụng được mã ưu đãi cho đơn này.'


class _DryRunDone(Exception):
    """Dùng để thoát savepoint của lần áp thử, mang theo kết quả."""

    def __init__(self, error):
        super().__init__(error)
        self.error = error


def voucher_apply_error(order, code):
    """Áp mã `code` vào đơn nháp `order`.

    Trả '' nếu áp được (dòng thưởng đã nằm trên đơn), hoặc câu lỗi cho khách nếu
    không. Chạy trong savepoint nên khi lỗi đơn trở về như trước lúc áp.
    """
    if not hasattr(order, 'action_apply_loyalty_voucher'):
        return 'Hệ thống ưu đãi chưa được kích hoạt.'
    try:
        with order.env.cr.savepoint():
            order.loyalty_voucher_code = code
            order.action_apply_loyalty_voucher()
    except UserError as e:
        return e.args[0] if e.args else GENERIC_ERROR
    except Exception:
        _logger.exception('Áp voucher %s vào đơn %s lỗi', code, order.name)
        return GENERIC_ERROR
    return ''


def voucher_dry_run_error(env, order_vals, code):
    """Áp thử mã `code` lên một đơn dựng từ `order_vals` rồi hoàn lại toàn bộ.

    Dùng trước khi khách thanh toán, lúc chưa có đơn thật. Trả '' nếu áp được,
    hoặc câu lỗi cho khách. Không để lại bản ghi nào.
    """
    vals = dict(order_vals)
    # Đặt tên sẵn để không tiêu số thứ tự đơn bán (sequence không rollback được)
    vals['name'] = 'ZALO-VOUCHER-CHECK'
    vals['order_line'] = [(0, 0, dict(line[2])) for line in order_vals.get('order_line', [])]
    try:
        with env.cr.savepoint():
            order = env['sale.order'].sudo().create(vals)
            raise _DryRunDone(voucher_apply_error(order, code))
    except _DryRunDone as done:
        return done.error
