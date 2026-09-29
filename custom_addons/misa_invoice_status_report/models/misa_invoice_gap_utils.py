"""Hàm thuần phân loại phần "còn lại chưa xuất HĐ" của từng phiếu — không đụng env/ORM."""

# Thứ tự ở đây là thứ tự hiện trên màn hình. 'counted' = có cộng vào "Còn lại chưa xuất HĐ".
GAP_CATEGORIES = [
    {
        'key': 'no_invoice', 'counted': True,
        'label': 'Chưa có hóa đơn',
        'hint': 'Đã xuất kho nhưng chưa có đề nghị/hóa đơn nào phủ phiếu này.',
        'action': 'Lập đề nghị xuất HĐ trên MISA, ghi đúng số phiếu xuất kho.',
    },
    {
        'key': 'partial_elsewhere', 'counted': True,
        'label': 'Mới có HĐ một phần',
        'hint': 'Một phần hàng của phiếu đã nằm trong đề nghị của phiếu khác, phần còn lại chưa có HĐ.',
        'action': 'Lập đề nghị cho phần hàng còn lại.',
    },
    {
        'key': 'invoice_short', 'counted': True,
        'label': 'Có HĐ nhưng thiếu tiền',
        'hint': 'Tiền hóa đơn ít hơn tiền xuất kho — xuất HĐ thiếu hàng, hoặc khớp nhầm sang đề nghị nhỏ hơn.',
        'action': 'Mở chi tiết đề nghị, so từng dòng hàng với phiếu xuất kho.',
    },
    {
        'key': 'invoice_over', 'counted': True,
        'label': 'HĐ nhiều hơn xuất kho',
        'hint': 'Tiền hóa đơn lớn hơn tiền xuất kho — thường do hàng trả lại chưa điều chỉnh HĐ, '
                'hoặc đề nghị gộp cả hàng của phiếu chưa xuất kho/ngoài phạm vi.',
        'action': 'Kiểm tra hàng trả và các phiếu trong đề nghị gộp.',
    },
    {
        'key': 'shopee', 'counted': True,
        'label': 'Đơn Shopee chưa đủ HĐĐT',
        'hint': 'Đơn Shopee chưa có hoặc chưa đủ hóa đơn điện tử meInvoice.',
        'action': 'Xem tab Đơn Shopee.',
    },
    {
        'key': 'customs', 'counted': True,
        'label': 'HĐ hải quan chưa khớp phiếu',
        'hint': 'Hóa đơn hải quan đã xuất nhưng chưa khớp phiếu xuất kho nào — đang được trừ tạm vào phần còn lại.',
        'action': 'Xem tab Đơn hải quan, khớp dòng hóa đơn với phiếu.',
    },
    {
        'key': 'rounding', 'counted': True,
        'label': 'Sai số làm tròn',
        'hint': 'Cộng dồn các chênh lệch nhỏ dưới 1 đ trên từng phiếu.',
        'action': 'Không cần xử lý.',
    },
    {
        'key': 'resolved', 'counted': False,
        'label': 'Đã xác minh xong',
        'hint': 'Đã xác minh qua MISA: tiền nằm ở hóa đơn khác — không tính vào phần còn lại.',
        'action': 'Không cần xử lý.',
    },
]
GAP_CATEGORY_BY_KEY = {cat['key']: cat for cat in GAP_CATEGORIES}


def classify_misa_picking_gap(invoiced, gap_resolved, gap, allocated, tolerance):
    """Xếp phần lệch (tiền xuất kho − tiền HĐ quy về phiếu) của 1 phiếu MISA vào 1 nhóm.

    Nhận: invoiced (phiếu có misa_invoice_state='invoiced'), gap_resolved, gap, allocated
    (tiền HĐ quy về phiếu), tolerance (dung sai đ).
    Trả: key trong GAP_CATEGORIES, hoặc None khi |gap| <= tolerance (coi như khớp — người gọi
    tự cộng vào 'rounding'). Phiếu đã xác minh xong luôn trả 'resolved' (kể cả lệch nhỏ) vì
    toàn bộ phần lệch của nó đã được loại khỏi ô tổng.
    """
    if invoiced and gap_resolved:
        return 'resolved'
    if abs(gap) <= tolerance:
        return None
    if gap < 0:
        return 'invoice_over'
    if invoiced:
        return 'invoice_short'
    return 'partial_elsewhere' if allocated > tolerance else 'no_invoice'


def month_key(day):
    """'YYYY-MM' của 1 date; None/False trả ''."""
    return day.strftime('%Y-%m') if day else ''
