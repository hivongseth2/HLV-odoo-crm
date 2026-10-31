# -*- coding: utf-8 -*-
"""Quy tắc dùng lại thông số trợ lý đã tra trên web.

Util thuần: vào giá trị thường, ra giá trị thường. Không đụng ``self.env``.
"""

# Quá hạn này thì tra web lại: hãng đổi đời máy / sửa thông số khá nhanh.
SPEC_FRESH_DAYS = 20
# Đủ cho 5-12 thông số + vài link; dài hơn thường là Claude chép nguyên trang.
MAX_SPEC_CHARS = 3000
MAX_SOURCE_CHARS = 1500
MAX_LOOKUP_CODES = 10


def spec_age_days(checked_at, now):
    """Số ngày từ lần tra tới giờ.

    Nhận: checked_at, now là ``datetime`` (cùng múi giờ). Trả: số ngày nguyên, không âm.
    Biên: checked_at rỗng -> None (chưa từng tra).
    """
    if not checked_at:
        return None
    return max(0, (now - checked_at).days)


def is_fresh(checked_at, now, days=SPEC_FRESH_DAYS):
    """Thông số đã lưu còn dùng được không.

    Nhận: checked_at, now là ``datetime``; days = hạn (ngày). Trả: True khi đã tra và chưa quá hạn.
    Biên: chưa từng tra -> False; đúng bằng hạn -> vẫn còn dùng.
    """
    age = spec_age_days(checked_at, now)
    return age is not None and age <= days


def clean_text(text, limit):
    """Chữ đã cắt khoảng trắng hai đầu và cắt bớt cho vừa ô lưu.

    Nhận: chuỗi hoặc None, giới hạn ký tự. Trả: chuỗi.
    Biên: None / toàn khoảng trắng -> ""; dài quá -> cắt còn đúng ``limit`` ký tự.
    """
    return (text or "").strip()[:limit]


def lookup_codes(codes):
    """Danh sách mã cần tra thông số đã lưu, bỏ rỗng, bỏ trùng, giữ thứ tự.

    Nhận: list chuỗi (hoặc một chuỗi). Trả: list chuỗi đã strip, tối đa MAX_LOOKUP_CODES.
    Biên: None / rỗng -> [].
    """
    if isinstance(codes, str):
        codes = [codes]
    seen, result = set(), []
    for code in codes or []:
        code = (code or "").strip() if isinstance(code, str) else ""
        if code and code.upper() not in seen:
            seen.add(code.upper())
            result.append(code)
    return result[:MAX_LOOKUP_CODES]
