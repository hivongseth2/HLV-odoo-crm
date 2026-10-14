# -*- coding: utf-8 -*-
"""Số hợp đồng theo khuôn của từng mẫu, ví dụ "{dd}{mm}{yyyy}/HLV-{ma_khach}" -> "14102026/HLV-SGAT".

Chỗ thay trong khuôn:
  {dd} {mm} {yyyy} {yy}  ngày soạn hợp đồng
  {seq}                  số thứ tự theo loại hợp đồng trong năm (001, 002…), chỉ cấp khi khuôn có
  {ma_khach}             mã viết tắt công ty khách (xem customer_code)
  {bao_gia}              số báo giá CRM hàng của văn bản lấy từ đó (BG302982035), chưa có -> rỗng

build_number(pattern, day, seq, code, quote='') -> chuỗi số hợp đồng. Khuôn rỗng -> "/".
follows_inputs(pattern) -> True nếu số đổi theo khách / báo giá và không lấy số thứ tự, tức là cấp
    lại được khi người soạn đổi khách hoặc báo giá (lấy lại số thứ tự thì làm thủng dãy số).
customer_code(registry, name) -> mã khách: ưu tiên mã khai trên khách (company_registry), không có
    thì tự viết tắt tên công ty ("CÔNG TY TNHH SÀI GÒN ALLIED TECHNOLOGIES" -> "SGAT"). Không có gì -> "KH".
unique_number(number, exists) -> number, hoặc number-2, number-3… cho tới khi exists(...) là False.
"""

import re
import unicodedata

_PLACEHOLDER_RE = re.compile(r'\{(dd|mm|yyyy|yy|seq|ma_khach|bao_gia)\}')
# Chữ chỉ loại hình doanh nghiệp, không đưa vào viết tắt
_LEGAL_WORDS = {
    'CONG', 'TY', 'CTY', 'TNHH', 'CO', 'PHAN', 'CP', 'MTV', 'MOT', 'THANH', 'VIEN', 'CHI', 'NHANH', 'TAI',
    'DOANH', 'NGHIEP', 'TU', 'NHAN', 'DNTN', 'HKD', 'HO', 'KINH', 'TAP', 'DOAN', 'VA', 'THUONG', 'MAI',
    'DICH', 'VU', 'SAN', 'XUAT', 'CO.,LTD', 'LTD', 'JSC', 'COMPANY', 'LIMITED',
}
_MAX_CODE = 6


def uses_sequence(pattern):
    return '{seq}' in (pattern or '')


def follows_inputs(pattern):
    """Xem docstring đầu module."""
    pattern = pattern or ''
    return not uses_sequence(pattern) and ('{ma_khach}' in pattern or '{bao_gia}' in pattern)


def _ascii_upper(text):
    text = unicodedata.normalize('NFD', (text or '').replace('đ', 'd').replace('Đ', 'D'))
    return ''.join(ch for ch in text if not unicodedata.combining(ch)).upper()


def customer_code(registry, name):
    """Xem docstring đầu module."""
    code = re.sub(r'\s+', '', _ascii_upper(registry))
    if code:
        return code
    words = [w for w in re.findall(r'[A-Z0-9]+', _ascii_upper(name)) if w not in _LEGAL_WORDS]
    return ''.join(w[0] for w in words)[:_MAX_CODE] or 'KH'


def build_number(pattern, day, seq, code, quote=''):
    """Xem docstring đầu module. day: datetime.date; seq: số thứ tự (int) hoặc None."""
    if not pattern:
        return '/'
    values = {
        'dd': '%02d' % day.day,
        'mm': '%02d' % day.month,
        'yyyy': str(day.year),
        'yy': '%02d' % (day.year % 100),
        'seq': '%03d' % seq if seq else '',
        'ma_khach': code or '',
        'bao_gia': (quote or '').strip(),
    }
    return _PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], pattern)


def unique_number(number, exists):
    """Xem docstring đầu module."""
    candidate, index = number, 2
    while exists(candidate):
        candidate = '%s-%d' % (number, index)
        index += 1
    return candidate
