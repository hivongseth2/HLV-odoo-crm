"""Hàm dùng chung cho module điều phối.

Phần chuẩn hoá tên / đọc toạ độ đã chuyển sang addon ``hlv_geo_utils`` vì module đi nhận
hàng (``hlv_purchase_pickup``) cũng cần đúng các hàm đó: cùng một địa chỉ phải ra cùng một
khoá so khớp ở cả hai chiều giao và nhận. Ở đây chỉ re-export để mọi call site cũ
(``from .dispatch_utils import normalize_name``) không phải sửa.

``split_codes`` ở lại đây: mã sale MISA là chuyện riêng của điều phối, không phải chuyện
địa lý.
"""

from odoo.addons.hlv_geo_utils.tools.geo_text import (
    normalize_name,
    parse_latlng,
    strip_accents,
)

__all__ = ['normalize_name', 'parse_latlng', 'strip_accents', 'split_codes']


def split_codes(value):
    """Tách chuỗi nhiều mã sale MISA phân tách bởi dấu phẩy."""
    out = []
    seen = set()
    for part in (value or '').split(','):
        code = part.strip()
        if code and code.upper() not in seen:
            seen.add(code.upper())
            out.append(code)
    return out
