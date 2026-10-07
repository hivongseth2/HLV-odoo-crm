# -*- coding: utf-8 -*-
"""Hàm thuần đọc các cờ trên CHỨNG TỪ BÁN HÀNG MISA (sa_voucher_get).

Đặt ở module này (nơi có lớp gọi API MISA) để mọi module đọc chứng từ bán hàng — kiểm thu
tiền cho Loyalty, công nợ phải thu — dùng chung đúng 1 cách hiểu paid_type.
"""

# MISA trả paid_type ngay trên chứng từ bán hàng (sa_voucher_get): 1 = đã thu tiền,
# 0 = chưa thu. Giá trị khác (MISA có thể thêm) KHÔNG đoán bừa — xem paid_state_of().
PAID_TYPE_PAID = 1
PAID_TYPE_UNPAID = 0


def paid_state_of(paid_type):
    """Quy paid_type của MISA về (state, label) để hiển thị.

    Nhận int/str/None. Trả ('paid'|'unpaid'|'unknown', <nhãn tiếng Việt>). paid_type không đọc
    được (None, rỗng, giá trị lạ) trả 'unknown' kèm giá trị thô — thà nói "không rõ" còn hơn
    đoán bừa thành "chưa thu" rồi để kế toán đi đòi tiền một đơn đã thu.
    """
    try:
        value = int(paid_type)
    except (TypeError, ValueError):
        return ('unknown', 'Không rõ (paid_type=%s)' % (paid_type,))
    if value == PAID_TYPE_PAID:
        return ('paid', 'Đã thu tiền')
    if value == PAID_TYPE_UNPAID:
        return ('unpaid', 'Chưa thu tiền')
    return ('unknown', 'Không rõ (paid_type=%s)' % (value,))
