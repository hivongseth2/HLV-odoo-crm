# -*- coding: utf-8 -*-
"""Danh sách biến merge và cách định dạng giá trị cho hợp đồng.

Tên biến giữ nguyên như form Excel và mẫu Word cũ (Ten_Ben_Mua, Don_Gia_1...) để
mẫu cũ chạy được không cần sửa.

build_vars(values) nhận giá trị thô (date, số, chuỗi) và trả về dict toàn chuỗi đã
định dạng cho mọi biến trong VARIABLE_NAMES, cộng biến dòng hàng thứ 11 trở đi nếu có.
Thiếu giá trị -> chuỗi rỗng, không bao giờ để lọt None hay tên biến chưa điền.
Trường hợp biên: ngày None -> chuỗi rỗng cho Ngay/Thang/Nam; không giới hạn số dòng hàng
(mẫu có ít dòng hơn thì docx_merge nhân bản dòng cuối).
"""

import re

from decimal import Decimal, ROUND_HALF_UP

from .amount_words import amount_in_words_vi

# Số dòng hàng có sẵn trong mẫu Word gốc; dùng cho bảng biến và cột Excel tối thiểu
LINE_COUNT = 10

HEADER_VARIABLES = [
    'So_Hop_Dong', 'Ngay_Ky', 'Thang_Ky', 'Nam_Ky',
    'Ten_Ben_Mua', 'Dia_Chi_Ben_Mua', 'Ma_So_Thue_Ben_Mua', 'Dien_Thoai_Ben_Mua',
    'Fax_Ben_Mua', 'Nguoi_Dai_Dien_Ben_Mua', 'Chuc_Vu_Ben_Mua',
    'Thoi_Gian_Giao_Hang', 'Dia_Diem_Giao_Hang', 'Dieu_Kien_Thanh_Toan',
    'Ngay_Het_Han', 'Toa_An_Giai_Quyet', 'Mat_Hang_Chinh',
]
TOTAL_VARIABLES = [
    'Tong_Tien_Hang', 'Thue_Suat_VAT', 'Tien_Thue_VAT',
    'Tong_Gia_Tri_HD', 'Tong_Gia_Tri_Bang_Chu',
]
SELLER_VARIABLES = [
    'Ten_Ben_Ban', 'Dia_Chi_Ben_Ban', 'Dien_Thoai_Ben_Ban', 'Ma_So_Thue_Ben_Ban',
    'Nguoi_Dai_Dien_Ben_Ban', 'Chuc_Vu_Ben_Ban', 'Tai_Khoan_Ben_Ban', 'Ngan_Hang_Ben_Ban',
]
LINE_FIELDS = ['Ten_Hang', 'DVT', 'So_Luong', 'Don_Gia', 'Thanh_Tien']
LINE_VARIABLE_RE = re.compile(r'^(%s)_(\d+)$' % '|'.join(LINE_FIELDS))
LINE_VARIABLES = ['%s_%d' % (f, i) for i in range(1, LINE_COUNT + 1) for f in LINE_FIELDS]

VARIABLE_NAMES = HEADER_VARIABLES + TOTAL_VARIABLES + SELLER_VARIABLES + LINE_VARIABLES

# Nhãn tiếng Việt cho màn hình chọn biến khi soạn mẫu
VARIABLE_LABELS = {
    'So_Hop_Dong': 'Số hợp đồng',
    'Ngay_Ky': 'Ngày ký (dd)', 'Thang_Ky': 'Tháng ký', 'Nam_Ky': 'Năm ký',
    'Ten_Ben_Mua': 'Tên bên mua', 'Dia_Chi_Ben_Mua': 'Địa chỉ bên mua',
    'Ma_So_Thue_Ben_Mua': 'MST bên mua', 'Dien_Thoai_Ben_Mua': 'Điện thoại bên mua',
    'Fax_Ben_Mua': 'Fax bên mua', 'Nguoi_Dai_Dien_Ben_Mua': 'Người đại diện bên mua',
    'Chuc_Vu_Ben_Mua': 'Chức vụ bên mua',
    'Thoi_Gian_Giao_Hang': 'Thời gian giao hàng', 'Dia_Diem_Giao_Hang': 'Địa điểm giao hàng',
    'Dieu_Kien_Thanh_Toan': 'Điều kiện thanh toán', 'Ngay_Het_Han': 'Ngày hết hạn',
    'Toa_An_Giai_Quyet': 'Toà án giải quyết tranh chấp', 'Mat_Hang_Chinh': 'Mặt hàng chính',
    'Tong_Tien_Hang': 'Tổng tiền hàng', 'Thue_Suat_VAT': 'Thuế suất VAT (%)',
    'Tien_Thue_VAT': 'Tiền thuế VAT', 'Tong_Gia_Tri_HD': 'Tổng giá trị HĐ',
    'Tong_Gia_Tri_Bang_Chu': 'Tổng giá trị bằng chữ',
    'Ten_Ben_Ban': 'Tên bên bán', 'Dia_Chi_Ben_Ban': 'Địa chỉ bên bán',
    'Dien_Thoai_Ben_Ban': 'Điện thoại bên bán', 'Ma_So_Thue_Ben_Ban': 'MST bên bán',
    'Nguoi_Dai_Dien_Ben_Ban': 'Người đại diện bên bán', 'Chuc_Vu_Ben_Ban': 'Chức vụ bên bán',
    'Tai_Khoan_Ben_Ban': 'Số tài khoản bên bán', 'Ngan_Hang_Ben_Ban': 'Ngân hàng bên bán',
}

for _i in range(1, LINE_COUNT + 1):
    VARIABLE_LABELS.update({
        'Ten_Hang_%d' % _i: 'Tên hàng dòng %d' % _i,
        'DVT_%d' % _i: 'ĐVT dòng %d' % _i,
        'So_Luong_%d' % _i: 'Số lượng dòng %d' % _i,
        'Don_Gia_%d' % _i: 'Đơn giá dòng %d' % _i,
        'Thanh_Tien_%d' % _i: 'Thành tiền dòng %d' % _i,
    })


def is_known_variable(name):
    """True nếu name là biến module điền được (kể cả dòng hàng số bất kỳ, ví dụ Ten_Hang_25)."""
    return name in VARIABLE_NAMES or bool(LINE_VARIABLE_RE.match(name or ''))


def format_money(amount):
    """Số tiền -> '39.476.160'. None/'' -> ''. Làm tròn nửa lên về đồng nguyên, cùng cách
    với amount_in_words_vi (round() của Python làm tròn kiểu ngân hàng: 1498,5 -> 1498)."""
    if amount in (None, ''):
        return ''
    value = int(Decimal(str(amount)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return '{:,}'.format(value).replace(',', '.')


def format_number(number):
    """Số lượng/thuế suất -> '4' hoặc '7,5' (dấu phẩy thập phân kiểu Việt). Bỏ số 0 thừa."""
    if number in (None, ''):
        return ''
    value = float(number)
    if value.is_integer():
        return str(int(value))
    return ('%s' % round(value, 4)).rstrip('0').replace('.', ',')


def build_vars(values):
    """Dựng dict biến từ giá trị thô.

    values: dict khoá đúng tên biến (HEADER_VARIABLES, SELLER_VARIABLES, TOTAL_VARIABLES
    không cần vì tổng được tính lại ở đây). 'Ngay_Ky' là datetime.date. 'lines' là list
    dict {'Ten_Hang','DVT','So_Luong','Don_Gia','Thanh_Tien'} (không giới hạn); Thanh_Tien thiếu
    thì tự tính từ So_Luong * Don_Gia. 'Thue_Suat_VAT' là số phần trăm (ví dụ 8).
    """
    lines = list(values.get('lines') or [])
    out = {name: '' for name in VARIABLE_NAMES}
    for name in HEADER_VARIABLES + SELLER_VARIABLES:
        if values.get(name) not in (None, False):
            out[name] = str(values[name])

    contract_date = values.get('Ngay_Ky')
    if contract_date:
        out['Ngay_Ky'] = str(contract_date.day)
        out['Thang_Ky'] = str(contract_date.month)
        out['Nam_Ky'] = str(contract_date.year)

    total_untaxed = 0.0
    for idx, line in enumerate(lines, start=1):
        qty = line.get('So_Luong')
        price = line.get('Don_Gia')
        subtotal = line.get('Thanh_Tien')
        if subtotal in (None, '') and qty not in (None, '') and price not in (None, ''):
            subtotal = float(qty) * float(price)
        out['Ten_Hang_%d' % idx] = line.get('Ten_Hang') or ''
        out['DVT_%d' % idx] = line.get('DVT') or ''
        out['So_Luong_%d' % idx] = format_number(qty)
        out['Don_Gia_%d' % idx] = format_money(price)
        out['Thanh_Tien_%d' % idx] = format_money(subtotal)
        total_untaxed += float(subtotal or 0)

    vat_rate = float(values.get('Thue_Suat_VAT') or 0)
    vat_amount = total_untaxed * vat_rate / 100
    grand_total = total_untaxed + vat_amount
    out['Tong_Tien_Hang'] = format_money(total_untaxed)
    out['Thue_Suat_VAT'] = format_number(vat_rate)
    out['Tien_Thue_VAT'] = format_money(vat_amount)
    out['Tong_Gia_Tri_HD'] = format_money(grand_total)
    out['Tong_Gia_Tri_Bang_Chu'] = amount_in_words_vi(grand_total)
    return out
