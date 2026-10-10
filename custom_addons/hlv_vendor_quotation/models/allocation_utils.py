# -*- coding: utf-8 -*-
"""Hàm thuần chia số lượng mua một sản phẩm giữa nhiều NCC (phiếu hỏi giá) — không đụng env.

Một sản phẩm của phiếu có "SL cần mua" (need); sale chọn một hay nhiều NCC, mỗi NCC một "SL mua".
NCC không đủ hàng khai "có ngay" + hẹn ngày giao phần còn lại, hoặc "không có thêm"
(vendor_quote_utils.read_availability).
"""

from .vendor_quote_utils import format_vn_number


def supply_cap(available_qty, no_more):
    """SL tối đa mua được của một NCC.

    Chỉ có giới hạn khi NCC báo "có X · không có thêm" (available_qty > 0 và no_more) → available_qty.
    Có đủ, hoặc thiếu nhưng hẹn giao phần còn lại → None (không giới hạn).
    """
    return available_qty if available_qty and no_more else None


def default_buy_qty(need_qty, others_qty, available_qty, no_more):
    """SL mua điền sẵn khi sale bấm chọn thêm một NCC.

    = phần còn thiếu (need_qty − SL đã chia cho các NCC khác, không âm), không quá supply_cap của NCC.
    Đã chia đủ → 0.0. need_qty / others_qty None coi như 0.
    """
    rest = max(0.0, (need_qty or 0.0) - (others_qty or 0.0))
    cap = supply_cap(available_qty, no_more)
    return rest if cap is None else min(rest, cap)


def buy_qty_error(qty, ordered_qty, cap):
    """Kiểm SL mua mới của một NCC.

    qty: số sale nhập (None / NaN / ≤ 0 là sai — không mua của NCC này thì bỏ chọn); ordered_qty: phần
    đã lên RFQ / đơn mua (không giảm dưới số này); cap: supply_cap (None = không giới hạn).
    Trả câu lỗi (không có tên sản phẩm — nơi gọi thêm), hoặc "" khi hợp lệ.
    """
    if qty is None or qty != qty or qty <= 0:
        return "SL mua phải lớn hơn 0 — không mua của NCC này thì bỏ chọn"
    if ordered_qty and qty < ordered_qty:
        return f"đã lên đơn mua {format_vn_number(ordered_qty)} — không giảm dưới số đó"
    if cap is not None and qty > cap:
        return f"NCC chỉ có {format_vn_number(cap)}"
    return ""


def split_buy_qty(qty, available_qty, backorder_date, no_more):
    """Tách SL mua của một NCC thành phần giao ngay và phần NCC hẹn — mỗi phần một dòng YCMH (khác
    "Ngày cần", để đơn mua ra 2 dòng theo ngày).

    Trả list (SL, ngày hẹn hoặc None). NCC thiếu hàng có hẹn ngày (available_qty > 0, backorder_date,
    không no_more) và mua nhiều hơn phần có ngay → [(available_qty, None), (phần còn lại, backorder_date)].
    Còn lại → [(qty, None)].
    """
    if backorder_date and not no_more and 0 < (available_qty or 0) < qty:
        return [(available_qty, None), (qty - available_qty, backorder_date)]
    return [(qty, None)]


def apply_qty_delta(main_qty, main_ordered, bo_qty, bo_ordered, delta, has_backorder):
    """SL mới của (dòng YCMH giao ngay, dòng YCMH phần hẹn) khi sale đổi SL mua của NCC đã lên YCMH.

    Đổi theo độ lệch (delta = SL mới − SL cũ) chứ không đặt thẳng: dòng YCMH có thể đã gộp hàng của
    phiếu khác. Tăng: cộng vào phần hẹn nếu có (has_backorder), không thì phần giao ngay. Giảm: bớt
    phần hẹn trước, rồi phần giao ngay; không phần nào giảm dưới SL đã lên đơn mua (*_ordered).
    Trả (main, bo) — bo = 0.0 khi không có phần hẹn; None khi không giảm được đủ.
    """
    main, bo = main_qty, (bo_qty if has_backorder else 0.0)
    if delta >= 0:
        return (main, bo + delta) if has_backorder else (main + delta, bo)
    take = -delta
    from_bo = min(take, max(0.0, bo - bo_ordered)) if has_backorder else 0.0
    from_main = take - from_bo
    if main - from_main < main_ordered - 1e-9:
        return None
    return main - from_main, bo - from_bo
