"""Hàm trình bày dùng chung của các service cho AI.

Quy ước của toàn bộ API cho AI, áp ở đây một lần:
- Thời điểm: chuỗi ISO 8601 UTC có hậu tố ``Z``. Ngày: ``YYYY-MM-DD``.
- Không có giá trị thì trả ``None`` chứ không trả chuỗi rỗng hay 0 — AI phải phân biệt
  được "chưa có dữ liệu" với "giá trị bằng 0".
- Tiền: số thực theo tiền tệ công ty (VND), không định dạng.
"""

from odoo import fields
from odoo.tools import html2plaintext

from ...tools.vtracking_partner import root_partner_name


def iso_datetime(value):
    """Datetime naive UTC của Odoo -> chuỗi ISO có ``Z``. Rỗng trả None."""
    return value.isoformat() + 'Z' if value else None


def iso_date(value):
    """Date -> ``YYYY-MM-DD``. Rỗng trả None."""
    return fields.Date.to_string(value) if value else None


def optional_field(record, field_name, default=None):
    """Giá trị của một field CÓ THỂ không tồn tại (field do Studio tạo trên bản cài này).

    Đọc qua ``_fields`` để module vẫn chạy ở nơi chưa tạo field đó. Giá trị rỗng trả
    ``default``.
    """
    if not record or field_name not in record._fields:
        return default
    return record[field_name] or default


def plain_text(html, limit=None):
    """HTML -> văn bản thuần đã cắt khoảng trắng. ``limit`` cắt bớt kèm dấu "…"."""
    text = (html2plaintext(html or '') or '').strip()
    if limit and len(text) > limit:
        return text[:limit - 1].rstrip() + '…'
    return text


def partner_block(partner):
    """Thông tin tối thiểu về một đối tác. Recordset rỗng trả None."""
    if not partner:
        return None
    return {
        'id': partner.id,
        'name': root_partner_name(partner),
        'contact_name': partner.name or None,
        'phone': partner.phone or partner.mobile or None,
    }


def one_line_address(partner):
    """Địa chỉ liên hệ của đối tác trên MỘT dòng, bỏ dòng tên ở đầu. Rỗng trả None.

    ``contact_address`` của Odoo mở đầu bằng tên khách; tên đó đã có ở ``partner_block``
    nên lặp lại ở đây chỉ làm chuỗi dài thêm.
    """
    if not partner:
        return None
    lines = [line.strip() for line in (partner.contact_address or '').split('\n') if line.strip()]
    if lines and lines[0] in (partner.name, partner.commercial_partner_id.name):
        lines = lines[1:]
    return ', '.join(lines) or None


def coords_block(latitude, longitude):
    """Cặp toạ độ ở dạng dict, hoặc None khi chưa có (0/0 coi là chưa có)."""
    if not latitude or not longitude:
        return None
    return {'latitude': latitude, 'longitude': longitude}
