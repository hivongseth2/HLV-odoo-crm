# -*- coding: utf-8 -*-
"""Hàm thuần đọc mã lỗi MISA trả về cho đề nghị sinh chứng từ."""


def _misa_error_text(parts):
    return ' '.join(str(part) for part in parts if part)


def misa_error_means_voucher_created(*parts):
    """MISA từ chối vì đề nghị đã được sinh chứng từ kế toán thật.

    Nhận: các mảnh của lỗi (error_code, error_message, chữ của exception...);
    mảnh rỗng/None bị bỏ qua. Trả: True nếu là lỗi IsCreatedVoucher; không có
    mảnh nào thì False.
    """
    text = _misa_error_text(parts)
    return 'IsCreatedVoucher' in text or 'Đã sinh chứng từ' in text


def misa_error_means_request_missing(*parts):
    """MISA không còn đề nghị nào mang org_refid đó (VoucherNotFound).

    Quan sát thực tế: sau lỗi này, gửi lại đúng org_refid cũ thì MISA nhận như
    đề nghị mới — tức bên MISA đã xóa sạch (thường là kế toán xóa trên giao diện,
    lúc đó MISA không gửi callback). Nhận/trả như misa_error_means_voucher_created.
    """
    text = _misa_error_text(parts)
    return 'VoucherNotFound' in text or 'Không tìm thấy đề nghị' in text
