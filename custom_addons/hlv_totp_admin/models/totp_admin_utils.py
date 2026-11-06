"""Hàm thuần cho 2FA do admin giữ khoá: không đụng env, không side effect."""
import base64
import io
import os
import re
import time
import urllib.parse

from odoo.addons.auth_totp.models.totp import ALGORITHM, DIGITS, TIMESTEP, TOTP_SECRET_SIZE, hotp


def generate_secret():
    """Sinh khoá TOTP mới.

    Trả: chuỗi base32 viết hoa, không dấu cách, cùng kích thước khoá core Odoo tự sinh
    (TOTP_SECRET_SIZE bit) nên app authenticator và _totp_check coi như khoá thường.
    """
    return base64.b32encode(os.urandom(TOTP_SECRET_SIZE // 8)).decode()


def format_secret(secret):
    """Chia khoá thành nhóm 4 ký tự cho dễ gõ tay. Nhận chuỗi rỗng / None trả ''."""
    clean = re.sub(r'\s', '', secret or '')
    return ' '.join(clean[i:i + 4] for i in range(0, len(clean), 4))


def build_otpauth_url(secret, login, issuer):
    """URL otpauth:// để quét QR.

    Nhận khoá base32 (có hay không có dấu cách đều được), login và tên hiển thị trong app.
    Trả chuỗi URL. Khoá rỗng thì trả '' (không dựng URL hỏng).
    """
    clean = re.sub(r'\s', '', secret or '').upper()
    if not clean:
        return ''
    label = urllib.parse.quote('%s:%s' % (issuer, login), safe=':')
    query = urllib.parse.urlencode({
        'secret': clean,
        'issuer': issuer,
        # Google Authenticator từ chối tên hash viết thường nên phải in hoa.
        'algorithm': ALGORITHM.upper(),
        'digits': DIGITS,
        'period': TIMESTEP,
    })
    return 'otpauth://totp/%s?%s' % (label, query)


def qr_png_b64(text):
    """Vẽ QR của `text`, trả PNG base64 (chuỗi). Text rỗng trả False để field Binary trống."""
    if not text:
        return False
    import qrcode  # import muộn: chỉ wizard cần, lỗi thiếu thư viện không làm hỏng cả module
    buf = io.BytesIO()
    qrcode.make(text.encode(), box_size=4).save(buf, optimise=True, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


def current_code(secret, now=None):
    """Mã 6 số hiện tại của khoá. Nhận khoá base32; `now` là timestamp giây (mặc định giờ máy).

    Trả chuỗi đủ DIGITS chữ số (có số 0 đứng đầu), '' nếu khoá rỗng.
    """
    clean = re.sub(r'\s', '', secret or '').upper()
    if not clean:
        return ''
    counter = int((time.time() if now is None else now) / TIMESTEP)
    return str(hotp(base64.b32decode(clean), counter)).zfill(DIGITS)

