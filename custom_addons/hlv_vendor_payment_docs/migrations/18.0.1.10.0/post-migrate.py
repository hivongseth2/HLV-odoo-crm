# -*- coding: utf-8 -*-
"""Sổ hoá đơn MISA lấy trước bản 18.0.1.10.0 gộp lệch làm tròn (hoá đơn MISA lớn hơn đơn Odoo vài chục – vài trăm
đồng vì làm tròn VAT khác nhau) vào "Đã trả qua ĐNC". Chuyển phần ≤ 1.000đ (payment_utils.ROUNDING_TOLERANCE) sang
"Lệch làm tròn", sửa luôn chữ trong ghi chú theo đơn. Phần lớn hơn để nguyên: có thể là ĐNC thật, không tách được nếu
không đọc lại MISA. Số tiền ghi công nợ trên phiếu không đổi — vẫn đúng."""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE hlv_misa_purchase_invoice
           SET rounding_amount = covered_amount,
               covered_amount = 0
         WHERE covered_amount > 0 AND covered_amount <= 1000
    """)
    # "đã trả qua ĐNC / phiếu khác 54" (số dưới 1.000, không có dấu chấm nghìn) → "lệch làm tròn 54".
    cr.execute(r"""
        UPDATE hlv_misa_purchase_invoice
           SET note = regexp_replace(note, 'đã trả qua ĐNC / phiếu khác ([0-9]{1,3})(?![0-9.])',
                                     'lệch làm tròn \1', 'g')
         WHERE note LIKE '%đã trả qua ĐNC / phiếu khác%'
    """)
