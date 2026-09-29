"""Hàm thuần quy đổi tiền dòng hàng hóa đơn MISA — không đụng env/ORM."""


def invoice_vat_ratio(invoice_total, line_amounts_before_vat):
    """Tỉ lệ (tổng tiền thanh toán / tổng tiền hàng chưa VAT) của 1 hóa đơn — chỉ dùng DỰ
    PHÒNG khi dòng hàng MISA trả về không có cột tiền VAT riêng.

    Nhận: invoice_total — total_amount của chứng từ bán hàng (đã gồm VAT, đã trừ chiết khấu);
    line_amounts_before_vat — amount_oc của TẤT CẢ dòng hàng trên hóa đơn đó.
    Trả: số nhân để đổi tiền 1 dòng chưa VAT sang có VAT (1.08, 1.1, hoặc 1.0 với hóa đơn
    0% VAT). Trả 1.0 khi thiếu dữ liệu (tổng <= 0 hoặc không có dòng).
    """
    base = sum(line_amounts_before_vat or [])
    if not invoice_total or invoice_total <= 0 or base <= 0:
        return 1.0
    return invoice_total / base


def pair_invoice_lines(stored_lines, fresh_lines):
    """Ghép dòng hải quan đã lưu với dòng vừa đọc lại từ MISA của CÙNG 1 hóa đơn.

    Nhận: stored_lines — list (id, order_code, inventory_item_code, quantity);
    fresh_lines — list dict có 'order_code', 'inventory_item_code', 'quantity'.
    Trả: {id: dict dòng MISA}. Ghép theo (mã đơn, mã hàng không phân biệt hoa/thường, số
    lượng); 2 dòng trùng hệt nhau thì ghép lần lượt, mỗi dòng MISA chỉ dùng 1 lần. Dòng đã lưu
    không còn trên hóa đơn MISA thì không có trong kết quả.
    """
    def key(order_code, item_code, quantity):
        return ((order_code or '').strip(), (item_code or '').strip().upper(), round(quantity or 0.0, 4))

    pool = {}
    for fresh in fresh_lines:
        pool.setdefault(key(fresh.get('order_code'), fresh.get('inventory_item_code'), fresh.get('quantity')), []).append(fresh)
    paired = {}
    for line_id, order_code, item_code, quantity in stored_lines:
        candidates = pool.get(key(order_code, item_code, quantity))
        if candidates:
            paired[line_id] = candidates.pop(0)
    return paired


def split_by_weights(total, weights):
    """Chia total theo tỉ lệ weights.

    Nhận: total — số tiền cần chia; weights — list số >= 0.
    Trả: list cùng độ dài weights, tổng đúng bằng total. Mọi weight bằng 0 thì chia đều;
    weights rỗng trả [].
    """
    if not weights:
        return []
    base = sum(weights)
    if base <= 0:
        return [total / len(weights)] * len(weights)
    return [total * weight / base for weight in weights]


def allocate_fifo(invoiced_total, parts):
    """Rót tiền hóa đơn của 1 đơn hàng vào các phiếu xuất kho, phiếu xuất trước nhận trước.

    Nhận: invoiced_total — tổng tiền đã xuất HĐ của đơn; parts — list (key, tiền xuất kho)
    đã xếp theo thứ tự ngày xuất kho.
    Trả: {key: tiền HĐ quy về}. Mỗi phiếu nhận tối đa bằng tiền xuất kho của nó; phần HĐ còn
    dư sau khi rót đủ mọi phiếu cộng vào phiếu CUỐI — tổng phân bổ luôn bằng tổng HĐ, phần dư
    hiện ra ở phiếu đó thành "HĐ nhiều hơn xuất kho" thay vì biến mất. invoiced_total <= 0 thì
    mọi phiếu 0; parts rỗng trả {}.
    """
    remaining = max(invoiced_total or 0.0, 0.0)
    result = {}
    for key, shipped in parts:
        take = min(remaining, max(shipped or 0.0, 0.0))
        result[key] = take
        remaining -= take
    if parts and remaining > 0:
        result[parts[-1][0]] += remaining
    return result


def voucher_line_amount_with_vat(line, fallback_ratio):
    """Tiền CÓ VAT của 1 dòng hàng chứng từ bán hàng MISA.

    Nhận: line — dict 1 dòng từ sa_voucher_get/get_paging_detail; fallback_ratio — kết quả
    invoice_vat_ratio của cả hóa đơn.
    Trả: amount_oc + vat_amount_oc − discount_amount_oc khi MISA trả cột vat_amount_oc (kể cả
    bằng 0 — hóa đơn 0% VAT); không có cột đó thì amount_oc × fallback_ratio.
    """
    amount = line.get('amount_oc') or 0.0
    if line.get('vat_amount_oc') is not None:
        return amount + (line.get('vat_amount_oc') or 0.0) - (line.get('discount_amount_oc') or 0.0)
    return amount * fallback_ratio
