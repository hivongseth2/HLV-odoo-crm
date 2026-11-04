# -*- coding: utf-8 -*-
"""Hàm thuần cho luồng thu mua đề xuất giá → sale hỏi lại NCC → thu mua duyệt (po_price_proposal.py) — không đụng env."""

from .vendor_quote_utils import format_vn_number

# Báo giá hỏi lại đã quá hạn: NCC có thêm từng này ngày để báo lại.
REQUOTE_DAYS = 2


def money_text(value):
    """Số tiền làm tròn tới đồng, kiểu VN: 1234567.8 → "1.234.568". None / 0 → "0"."""
    return format_vn_number(round(value or 0.0))


def requote_message(product_name, suggested_incl):
    """Tin sale gửi NCC (điền sẵn, sale sửa được trước khi gửi) xin báo lại giá một mặt hàng.

    suggested_incl: giá thu mua gợi ý, sau VAT (0 / None = không ghi giá). Lý do thu mua ghi là lời nội bộ cho sale,
    không đưa vào tin. Trả chuỗi một đoạn.
    """
    target = f" Bên mình mong giá khoảng {money_text(suggested_incl)} (sau VAT)." if suggested_incl else ""
    return (f"Nhờ quý công ty báo lại giá {product_name} trên báo giá này.{target} "
            "Quý công ty sửa đơn giá rồi bấm gửi báo giá giúp bên mình.")


def requote_restore_state(prev_state, current_state):
    """Trạng thái trả lại cho báo giá khi không còn món nào chờ NCC báo lại giá.

    prev_state: trạng thái báo giá trước khi mở cho NCC báo lại ("done" / "quoted" / "sent", "" = chưa mở);
    current_state: trạng thái hiện tại. Báo giá đã đóng ("done") thì đóng lại; đang "đã báo giá" mà NCC chưa gửi
    lại (vẫn "sent") thì về "quoted". Còn lại (NCC vừa gửi — đã là "quoted", hoặc chưa từng mở) → None = giữ nguyên.
    """
    if prev_state == "done":
        return "done"
    if prev_state == "quoted" and current_state == "sent":
        return "quoted"
    return None


def same_price_incl(price, tax_rate, discount, other_price, other_tax_rate, other_discount):
    """Hai cách ghi giá có ra cùng đơn giá SAU VAT, sau chiết khấu, làm tròn tới đồng không.

    price / other_price: đơn giá chưa VAT; tax_rate: % VAT; discount: % chiết khấu (None / 0 = không có). So theo giá
    sau VAT (giá bên mình đọc và chốt) nên cùng giá mà ghi thuế theo hai bản ghi thuế khác nhau vẫn coi là bằng.
    """
    def incl(net, tax, disc):
        return round((net or 0.0) * (1 - (disc or 0.0) / 100.0) * (1 + (tax or 0.0) / 100.0))
    return incl(price, tax_rate, discount) == incl(other_price, other_tax_rate, other_discount)


def same_money(value, other):
    """Hai số tiền bằng nhau khi làm tròn tới đồng (giá sau VAT tính lại từ giá chưa VAT lệch phần lẻ). None = 0."""
    return round(value or 0.0) == round(other or 0.0)


def vat_note(order_tax_rate, vendor_tax_rate):
    """Câu ghi chú khi NCC báo lại với % VAT khác VAT trên dòng đơn mua ("" khi bằng nhau).

    Duyệt thì giữ VAT của đơn, đơn giá chưa VAT tính lại để giá SAU VAT đúng bằng giá NCC báo.
    """
    if round(order_tax_rate or 0.0, 2) == round(vendor_tax_rate or 0.0, 2):
        return ""
    return (f"NCC báo VAT {format_vn_number(vendor_tax_rate or 0)}%, đơn đang VAT {format_vn_number(order_tax_rate or 0)}% "
            "— duyệt thì giữ VAT của đơn, giá sau VAT theo NCC báo.")
