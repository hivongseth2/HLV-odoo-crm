# -*- coding: utf-8 -*-
"""Hàm thuần đọc dữ liệu hàng trả về từ MISA CRM (search_product_by_name).

Util thuần: vào dict / chuỗi, ra giá trị. Không đụng ``self.env``, không side effect.
"""
import re

_TAX_RATE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_NON_ALNUM_RE = re.compile(r"[\W_]+")

# Tạo hàng thường ghi mô tả vào ô "Mô tả SP" (CustomField17) của CRM, ô này chỉ nhận 255 ký
# tự — quá là CRM từ chối. Schema tool trong hlv_product_agent/agent/misa_tools.py ghi cứng
# cùng con số (file đó chạy ngoài Odoo, không import được): đổi ở đây thì đổi cả ở đó.
PRODUCT_DESCRIPTION_MAX = 255


def description_length_error(description):
    """Câu báo lỗi khi mô tả hàng thường dài quá ô "Mô tả SP" của CRM.

    Nhận: chuỗi hoặc None. Trả: chuỗi lỗi (kèm độ dài hiện tại) nếu quá
    PRODUCT_DESCRIPTION_MAX ký tự, None nếu vừa. None / "" -> None.
    """
    length = len(description or "")
    if length <= PRODUCT_DESCRIPTION_MAX:
        return None
    return ("Mô tả tối đa %s ký tự (đang %s) — giới hạn ô Mô tả SP của MISA. Chỉ giữ các thông "
            "số chính rồi gửi lại." % (PRODUCT_DESCRIPTION_MAX, length))


def parse_tax_rate(tax_text):
    """% VAT trong chữ thuế của CRM.

    Nhận: chuỗi như "10%", "Thuế GTGT 8%", "KCT" hoặc None.
    Trả: float (10.0, 8.0, 0.0) hoặc None khi không có "%"(KCT / trống) — None = không gắn thuế.
    """
    match = _TAX_RATE_RE.search(str(tax_text or ""))
    return float(match.group(1).replace(",", ".")) if match else None


def code_key(code):
    """Mã hàng để so khớp: bỏ khoảng trắng / gạch / ký tự ngăn cách, không phân biệt hoa thường.

    Nhận: chuỗi hoặc None. Trả: chuỗi ("M18 FIW212-0X0" → "m18fiw2120x0"). None / "" → "".
    """
    return _NON_ALNUM_RE.sub("", str(code or "")).casefold()


def exact_code_match(results, code):
    """Hàng CRM có mã đúng bằng ``code`` (không phân biệt hoa thường, bỏ khoảng trắng hai đầu).

    Nhận: list dict kết quả CRM (khoá "code"), mã cần tìm. Trả: dict đó hoặc None.
    Không lấy hàng gần giống — tạo nhầm sản phẩm khó gỡ hơn báo "không thấy".
    """
    wanted = (code or "").strip().casefold()
    if not wanted:
        return None
    return next((p for p in results or [] if (p.get("code") or "").strip().casefold() == wanted), None)
