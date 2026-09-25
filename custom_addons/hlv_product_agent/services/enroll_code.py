# -*- coding: utf-8 -*-
"""Mã cài đặt dùng một lần cho máy chạy agent.

Không đụng ``self.env``, không side effect (ngoài việc lấy số ngẫu nhiên).
"""
import secrets

# Bỏ 0/O/1/I: người đọc mã qua điện thoại hoặc chép tay hay nhầm mấy ký tự này.
ENROLL_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
ENROLL_CODE_LENGTH = 8


def random_enroll_code():
    """Sinh mã dạng ``XXXX-XXXX`` cho dễ đọc.

    Trả: chuỗi 9 ký tự (8 ký tự mã + một gạch giữa).
    """
    raw = ''.join(secrets.choice(ENROLL_ALPHABET) for _ in range(ENROLL_CODE_LENGTH))
    return '%s-%s' % (raw[:4], raw[4:])


def normalize_enroll_code(code):
    """Chuẩn hóa mã người cài gõ vào để so sánh.

    Nhận: chuỗi bất kỳ hoặc None.
    Trả: mã in hoa, bỏ khoảng trắng và gạch.
    Biên: None / rỗng -> "".
    """
    return (code or '').strip().upper().replace('-', '').replace(' ', '')
