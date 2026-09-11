"""Hàm dùng chung cho module điều phối.

Chuẩn hoá tên khách là phần quan trọng nhất ở đây: Odoo sinh nhiều mã cho cùng một
khách (351 mã = 176 khách thật theo số liệu đối chiếu 01/06→10/09), và tên trên
Google My Maps viết khác tên trong Odoo. Mọi việc ghép bản đồ ↔ Odoo và mọi lần
re-import đều phải đi qua ``normalize_name`` để không sinh điểm trùng.
"""

import re
import unicodedata

# Tiền tố pháp nhân — bỏ đi trước khi so tên, vì bản đồ hay ghi "Jungwoo vina"
# trong khi Odoo ghi "Công Ty TNHH Jungwoo Vina".
_COMPANY_PREFIX_RE = re.compile(
    r'^(?:'
    r'cong\s*ty\s*(?:tnhh|co\s*phan|cp)?(?:\s*mtv)?(?:\s*mot\s*thanh\s*vien)?'
    r'|cty|c\.?\s*ty|congty'
    r'|nha\s*may|chi\s*nhanh|van\s*phong\s*dai\s*dien'
    r'|doanh\s*nghiep\s*tu\s*nhan|dntn'
    r'|co\.?,?\s*ltd|ltd|jsc|corp|corporation'
    r')\s+'
)

_NON_WORD_RE = re.compile(r'[^a-z0-9]+')
_LATLNG_RE = re.compile(
    r'^\s*(-?\d{1,3}(?:[.,]\d+)?)\s*[,;/\s]\s*(-?\d{1,3}(?:[.,]\d+)?)\s*$'
)


def strip_accents(value):
    """Bỏ dấu tiếng Việt, giữ nguyên chữ cái."""
    if not value:
        return ''
    decomposed = unicodedata.normalize('NFD', str(value))
    without_marks = ''.join(c for c in decomposed if unicodedata.category(c) != 'Mn')
    return without_marks.replace('đ', 'd').replace('Đ', 'D')


def normalize_name(value):
    """Khoá so khớp tên khách: bỏ dấu, bỏ tiền tố pháp nhân, bỏ ký tự không phải chữ/số.

    "Công Ty TNHH Jungwoo Vina" và "Jungwoo vina" đều ra "jungwoovina".
    """
    text = strip_accents(value or '').lower().strip()
    if not text:
        return ''
    # Chạy 2 lần vì có tên kiểu "Công ty TNHH MTV Nhà máy ..." lồng 2 tiền tố.
    for _ in range(2):
        stripped = _COMPANY_PREFIX_RE.sub('', text)
        if stripped == text:
            break
        text = stripped
    return _NON_WORD_RE.sub('', text)


def parse_latlng(value):
    """Nhận chuỗi "10.78950, 106.99179" (đúng dạng đang dùng trong dữ liệu bản đồ).

    Trả về (lat, lng) hoặc None nếu không parse được / ngoài khoảng hợp lệ.
    """
    if not value:
        return None
    match = _LATLNG_RE.match(str(value))
    if not match:
        return None
    try:
        lat = float(match.group(1).replace(',', '.'))
        lng = float(match.group(2).replace(',', '.'))
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        return None
    if not lat and not lng:
        return None
    return lat, lng


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
