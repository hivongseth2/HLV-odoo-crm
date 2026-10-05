# -*- coding: utf-8 -*-
"""Hàm thuần dựng dữ liệu hóa đơn meInvoice, dùng chung cho mọi kênh bán (Shopee, POS)."""

_ONES = ['', 'một', 'hai', 'ba', 'bốn', 'năm', 'sáu', 'bảy', 'tám', 'chín']
_UNITS = [(10 ** 9, 'tỷ'), (10 ** 6, 'triệu'), (10 ** 3, 'nghìn'), (1, '')]


def vat_rate_name(rate):
    """Tên thuế suất theo spec meInvoice cho một thuế suất phần trăm.

    Nhận: thuế suất dạng số (8.0 nghĩa là 8%). Trả: '0%', '5%', '8%', '10%';
    số âm → 'KKKNT' (không kê khai nộp thuế); thuế suất lạ → 'KHAC:x.x%'.
    None/0 → '0%'.
    """
    rate = float(rate or 0.0)
    if rate in (0.0, 5.0, 8.0, 10.0):
        return '%d%%' % rate
    if rate < 0:
        return 'KKKNT'
    return 'KHAC:%.1f%%' % rate


def seller_fields(company):
    """Các trường người bán (Seller*) của InvoiceData, lấy từ công ty bán hàng.

    Nhận: bản ghi res.company (chỉ đọc thuộc tính, không ghi). Trả: dict 5 khóa
    SellerLegalName/TaxCode/Address/PhoneNumber/Email; thiếu dữ liệu → chuỗi rỗng.
    Địa chỉ ưu tiên địa chỉ đầy đủ của partner công ty, không có thì lấy street.
    """
    return {
        'SellerLegalName': company.name or '',
        'SellerTaxCode': company.vat or '',
        'SellerAddress': company.partner_id.contact_address_complete or company.street or '',
        'SellerPhoneNumber': company.phone or '',
        'SellerEmail': company.email or '',
    }


def _read_group_vi(group, is_first):
    """Đọc một nhóm 3 chữ số (0-999). Nhóm đầu không đọc 'không trăm'/'lẻ'."""
    if group == 0:
        return ''
    hundreds, rest = divmod(group, 100)
    tens, units = divmod(rest, 10)
    parts = []
    if hundreds:
        parts.append(_ONES[hundreds] + ' trăm')
    elif not is_first:
        parts.append('không trăm')
    if tens == 1:
        text = 'mười'
        if units == 5:
            text += ' lăm'
        elif units:
            text += ' ' + _ONES[units]
        parts.append(text)
    elif tens > 1:
        text = _ONES[tens] + ' mươi'
        if units == 1:
            text += ' mốt'
        elif units == 5:
            text += ' lăm'
        elif units:
            text += ' ' + _ONES[units]
        parts.append(text)
    elif units:
        if hundreds or not is_first:
            parts.append('lẻ ' + _ONES[units])
        else:
            parts.append(_ONES[units])
    return ' '.join(parts)


def amount_in_words_vi(amount):
    """Đọc số tiền VND thành chữ tiếng Việt cho ô 'Số tiền bằng chữ'.

    Nhận: số tiền (int/float/None), làm tròn tới đồng. Trả: chuỗi viết hoa chữ
    đầu, kết thúc bằng ' đồng', ví dụ 1500000 → 'Một triệu năm trăm nghìn đồng'.
    0/None → 'Không đồng'. Số âm đọc theo giá trị tuyệt đối.
    """
    remaining = abs(int(round(float(amount or 0))))
    if remaining == 0:
        return 'Không đồng'

    parts = []
    for divisor, unit_name in _UNITS:
        group = remaining // divisor
        remaining %= divisor
        if group == 0:
            continue
        text = _read_group_vi(group, is_first=not parts)
        parts.append((text + ' ' + unit_name).strip() if unit_name else text)

    result = ' '.join(parts)
    return result[:1].upper() + result[1:] + ' đồng'
