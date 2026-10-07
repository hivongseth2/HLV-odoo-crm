# -*- coding: utf-8 -*-
"""Mã sale MISA trên đơn bán — cùng field /giao-hang và /sale_plan dùng để biết đơn của ai.

Là field Studio nên không phải bản cài nào cũng có; mọi chỗ đọc mã sale đi qua đây.
"""

SALE_CODE_FIELD = "x_studio_misa_saler_code"


def has_sale_code(env):
    """Bản cài có field mã sale trên sale.order không."""
    return SALE_CODE_FIELD in env["sale.order"]._fields


def sale_code(order):
    """Mã sale của một đơn bán (đã sudo nếu cần). Không có đơn / không có field → ""."""
    if not order or SALE_CODE_FIELD not in order._fields:
        return ""
    return (order[SALE_CODE_FIELD] or "").strip()
