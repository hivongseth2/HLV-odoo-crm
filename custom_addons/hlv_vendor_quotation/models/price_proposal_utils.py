# -*- coding: utf-8 -*-
"""Hàm thuần cho luồng thu mua đề xuất giá → sale hỏi lại NCC → thu mua duyệt (po_price_proposal.py) — không đụng env."""

from .vendor_quote_utils import format_vn_number

# Báo giá hỏi lại đã quá hạn: NCC có thêm từng này ngày để báo lại.
REQUOTE_DAYS = 2


def money_text(value):
    """Số tiền làm tròn tới đồng, kiểu VN: 1234567.8 → "1.234.568". None / 0 → "0"."""
    return format_vn_number(round(value or 0.0))


def vat_rate(vat):
    """% VAT của mã VAT (VAT_SELECTION của báo giá NCC): "10" → 10.0, "kct" → 0.0, trống / None → None (không đổi)."""
    if not vat:
        return None
    return 0.0 if vat == "kct" else float(vat)


def vat_label(vat):
    """Chữ hiện cho mã VAT: "10" → "10%", "kct" → "không chịu thuế", trống → ""."""
    if not vat:
        return ""
    return "không chịu thuế" if vat == "kct" else f"{format_vn_number(float(vat))}%"


def requote_message(product_name, suggested_incl, new_qty_text="", replaces_name="", vat=""):
    """Tin gửi NCC xin báo lại giá một mặt hàng (soạn sẵn theo cái sale chốt; sale ghi thêm được).

    suggested_incl: giá mong muốn, sau VAT (0 / None = không ghi giá). new_qty_text: SL sẽ mua kèm ĐVT khi đổi SL / mã
    (VD "2 Cái"), "" = không nhắc SL. replaces_name: mã cũ khi đổi mã ("" = không đổi). vat: mã VAT bên mình muốn NCC
    xuất ("" = không nhắc). Lý do thu mua ghi là lời nội bộ, không đưa vào tin. Trả chuỗi một đoạn.
    """
    qty = f" cho số lượng {new_qty_text}" if new_qty_text else ""
    swap = f" (thay cho {replaces_name})" if replaces_name else ""
    target = f" Bên mình mong giá khoảng {money_text(suggested_incl)} (sau VAT)." if suggested_incl else ""
    tax = f" Hoá đơn VAT {vat_label(vat)}." if vat else ""
    return (f"Nhờ quý công ty báo lại giá {product_name}{swap}{qty} trên báo giá này.{target}{tax} "
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
