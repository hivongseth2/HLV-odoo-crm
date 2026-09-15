# -*- coding: utf-8 -*-
"""Hàm thuần dùng cho việc đối chiếu "hóa đơn MISA đã thu tiền chưa" với từng dòng hàng đã
tích điểm Loyalty.

Thuần theo đúng nghĩa: chỉ nhận dict/list/str, không đụng self.env, không gọi API, không side
effect — nhờ vậy phần logic khớp mã hàng/số hóa đơn kiểm chứng được mà không cần Odoo lẫn MISA.
"""

# MISA trả paid_type ngay trên chứng từ bán hàng (sa_voucher_get): 1 = đã thu tiền,
# 0 = chưa thu. Giá trị khác (MISA có thể thêm) KHÔNG đoán bừa — xem paid_state_of().
PAID_TYPE_PAID = 1
PAID_TYPE_UNPAID = 0

# Sai số cho phép khi so số lượng đã ghi trên hóa đơn với số lượng đã tích điểm (MISA và Odoo
# đều lưu số thực, cùng 1 con số vẫn lệch ở chữ số cuối sau vài phép nhân/chia).
QTY_TOLERANCE = 0.001


def normalize_code(value):
    """Chuẩn hóa mã hàng / mã đơn hàng trước khi so khớp: bỏ khoảng trắng 2 đầu + viết HOA.

    Nhận str/None/False. Trả str, '' nếu rỗng.
    """
    return (value or '').strip().upper()


def normalize_invoice_no(value):
    """Chuẩn hóa SỐ HÓA ĐƠN để so khớp.

    MISA trả inv_no đủ số 0 đứng đầu ("00005309") trong khi người dùng gõ tìm và dữ liệu lưu
    trên phiếu kho có thể là "005309" hoặc "5309" — bỏ hết số 0 đứng đầu để cả 3 dạng là MỘT.

    Nhận str/None/False. Trả str; '' nếu rỗng; '0' nếu chuỗi toàn số 0.
    """
    raw = normalize_code(value)
    if not raw:
        return ''
    return raw.lstrip('0') or '0'


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


def split_vouchers_by_invoice_no(page_data, inv_no):
    """Tách kết quả sa_voucher_get/paging_filter_v2 thành (đúng số hóa đơn, các dòng thừa).

    MISA tìm theo kiểu CHỨA trên 4 property cùng lúc nên 1 lần gọi có thể trả NHIỀU chứng từ:
    số hóa đơn khác cùng chứa chuỗi đang tìm ("005309" ra cả "1005309"), hoặc chính hóa đơn đó
    có nhiều bản. Chỉ dòng có inv_no khớp CHÍNH XÁC (sau normalize_invoice_no) mới được dùng để
    kết luận đã thu tiền; phần còn lại trả riêng cho người dùng tự xem, không tính vào kết luận.

    Nhận list dict (rỗng cũng được) + số hóa đơn cần tìm. Trả (matched, others) — 2 list.
    """
    target = normalize_invoice_no(inv_no)
    matched, others = [], []
    for row in page_data or []:
        if target and normalize_invoice_no(row.get('inv_no')) == target:
            matched.append(row)
        else:
            others.append(row)
    return matched, others


def index_voucher_lines(vouchers):
    """Dựng chỉ mục tra nhanh dòng chi tiết chứng từ MISA theo mã hàng.

    vouchers: list dict đã chuẩn hóa ở tầng model, mỗi cái cần có 'invoice_no', 'paid_state',
    'paid_label' và 'lines' (mỗi dòng có 'item_code', 'order_code', 'quantity', 'amount').

    Trả (by_order_item, by_item):
      - by_order_item: {(order_code, item_code): [entry, ...]} — khớp chặt theo đúng cặp
      - by_item: {item_code: [entry, ...]} — dự phòng khi hóa đơn ghi mã đơn hàng khác
    entry là chính dòng chi tiết đã kèm thông tin hóa đơn của nó. vouchers rỗng trả 2 dict rỗng.
    """
    by_order_item = {}
    by_item = {}
    for voucher in vouchers or []:
        for line in voucher.get('lines') or []:
            item_code = normalize_code(line.get('item_code'))
            if not item_code:
                continue
            entry = dict(
                line,
                invoice_no=voucher.get('invoice_no'),
                paid_state=voucher.get('paid_state'),
                paid_label=voucher.get('paid_label'),
            )
            by_order_item.setdefault((normalize_code(line.get('order_code')), item_code), []).append(entry)
            by_item.setdefault(item_code, []).append(entry)
    return by_order_item, by_item


def _combine_paid_states(entries):
    """Gộp trạng thái thu tiền của nhiều dòng hóa đơn cùng phục vụ 1 dòng hàng.

    Nhận list entry (đã có 'paid_state'). Trả 'paid' nếu TẤT CẢ đã thu, 'unpaid' nếu KHÔNG
    dòng nào đã thu, 'partial' nếu vừa có vừa không, 'unknown' nếu không đủ căn cứ. List rỗng
    trả 'not_found'.
    """
    if not entries:
        return 'not_found'
    states = {entry.get('paid_state') for entry in entries}
    if states == {'paid'}:
        return 'paid'
    if 'paid' in states:
        return 'partial'
    if states == {'unpaid'}:
        return 'unpaid'
    return 'unknown'


def match_loyalty_line(loyalty_line, by_order_item, by_item):
    """Tìm các dòng hóa đơn MISA ứng với 1 dòng hàng đã tích điểm.

    loyalty_line cần có 'item_code', 'order_code'.

    Ưu tiên khớp ĐÚNG cặp (đơn hàng, mã hàng). Không có mới khớp theo RIÊNG mã hàng và đánh
    dấu match_scope='code_only' — hóa đơn có mã hàng này nhưng ghi mã đơn hàng KHÁC, vẫn cho
    xem nhưng phải cảnh báo chứ không tự coi là đúng (case thật: 1 hóa đơn gộp nhiều đơn, hoặc
    sale ghi nhầm mã đơn lúc lập đề nghị xuất hóa đơn).

    Trả dict: {'match_scope': 'order_item'|'code_only'|'none', 'paid_state', 'invoiced_qty',
    'invoice_nos', 'entries'}. Không tìm thấy gì: match_scope='none', paid_state='not_found'.
    """
    item_code = normalize_code(loyalty_line.get('item_code'))
    order_code = normalize_code(loyalty_line.get('order_code'))

    entries = by_order_item.get((order_code, item_code)) or []
    match_scope = 'order_item' if entries else 'none'
    if not entries:
        entries = by_item.get(item_code) or []
        match_scope = 'code_only' if entries else 'none'

    invoice_nos = []
    for entry in entries:
        if entry.get('invoice_no') and entry['invoice_no'] not in invoice_nos:
            invoice_nos.append(entry['invoice_no'])

    return {
        'match_scope': match_scope,
        'paid_state': _combine_paid_states(entries),
        'invoiced_qty': sum(entry.get('quantity') or 0.0 for entry in entries),
        'invoice_nos': invoice_nos,
        'entries': entries,
    }


def qty_shortfall(loyalty_qty, invoiced_qty):
    """Phần số lượng đã tích điểm nhưng CHƯA thấy trên hóa đơn (0 nếu hóa đơn ghi đủ hoặc dư).

    Nhận 2 số (None coi như 0). Trả float >= 0, đã bỏ qua sai số QTY_TOLERANCE.
    """
    gap = (loyalty_qty or 0.0) - (invoiced_qty or 0.0)
    return gap if gap > QTY_TOLERANCE else 0.0


def summarize_line_states(line_states):
    """Kết luận chung cho cả giao dịch điểm từ trạng thái của từng dòng hàng.

    Nhận list state ('paid'/'unpaid'/'partial'/'unknown'/'not_found'). Trả (state, label):
    'paid' chỉ khi MỌI dòng đã thu tiền; 'unpaid' khi không dòng nào đã thu; 'partial' khi lẫn
    lộn; 'not_found' khi không dòng nào tìm thấy trên hóa đơn. List rỗng trả ('no_line', ...).
    """
    if not line_states:
        return ('no_line', 'Không có dòng hàng nào để đối chiếu')
    states = set(line_states)
    if states == {'paid'}:
        return ('paid', 'Đã thu tiền toàn bộ dòng hàng tích điểm')
    if states == {'not_found'}:
        return ('not_found', 'Không tìm thấy dòng hàng nào trên hóa đơn MISA')
    if 'paid' in states:
        return ('partial', 'Mới thu tiền một phần — còn dòng hàng chưa thu/chưa tìm thấy')
    if 'unpaid' in states:
        return ('unpaid', 'Chưa thu tiền')
    return ('unknown', 'Không xác định được tình trạng thu tiền')
