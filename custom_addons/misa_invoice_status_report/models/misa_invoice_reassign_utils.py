"""Hàm thuần tìm dòng đề nghị xuất HĐ bị sale ghi nhầm mã đơn — không đụng env/ORM."""

from collections import defaultdict

QTY_EPS = 0.001


def item_key(code):
    """Mã hàng chuẩn hóa để so Odoo với MISA: bỏ khoảng trắng 2 đầu, viết hoa. None/False → ''."""
    return (code or '').strip().upper()


def find_mislabeled_lines(lines, delivered, linked_pickings):
    """Dòng đề nghị ĐÃ phát hành HĐ ghi mã đơn X nhưng thật ra là hàng của phiếu P thuộc đơn Y
    (case thật: đề nghị KBC/OUT/09323 ghi QHTIG308 ×5 + TEFLON 3mm ×1 của KBC/OUT/12296 — đơn
    DH…235474 — vào DH…232207; đề nghị KBC/OUT/11810 ghi UT6581 ×2 cho DH…234991, 1 cái là của
    KBC/OUT/11375 — đơn DH…234488).

    Nhận:
      lines: list dict {key, refid, order, item, qty, issued} — MỌI dòng của các đề nghị đang xét,
        gồm cả đề nghị của đơn Y (order = mã đơn ghi trên dòng, item = item_key(mã hàng)).
      delivered: {mã đơn: {item: SL đã giao}} theo dòng đơn bán Odoo. Đơn không có trong đây coi
        như không biết — không chuyển dòng nào đi hay đến đơn đó.
      linked_pickings: {refid: [{picking, order, items: {item: SL xuất}}]} — phiếu xuất kho thuộc
        ĐÚNG 1 đơn đang gắn vào đề nghị refid.

    Chuyển dòng L (đơn X, mã i, SL q, đề nghị R) sang đơn Y khi đủ cả 4:
      1. Phiếu P của đơn Y ≠ X gắn vào R, và R không có dòng nào ghi mã Y — sale đã ghi mã Y ở
         dòng khác trên R thì dòng ghi X nhiều khả năng đúng là của X.
      2. P xuất đúng mã i với đúng SL q.
      3. X đang thừa HĐ mã i ít nhất q (SL đã phát hành HĐ ghi X − SL X đã giao ≥ q): bỏ dòng
         này đi X không bị thiếu.
      4. Y chưa đủ HĐ mã i (SL đã phát hành HĐ ghi Y + q ≤ SL Y đã giao): không đẩy Y thành thừa.
    Mỗi phiếu nhận mỗi mã hàng tối đa 1 dòng. Xét dòng theo thứ tự key để kết quả luôn như nhau.

    Trả {key dòng: (mã đơn Y, tên phiếu P)}; không dòng nào → {}.
    """
    invoiced = defaultdict(float)
    orders_on_request = defaultdict(set)
    for line in lines:
        orders_on_request[line['refid']].add(line['order'])
        if line['issued']:
            invoiced[(line['order'], line['item'])] += line['qty']

    moved = {}
    used = set()
    for line in sorted(lines, key=lambda l: str(l['key'])):
        source, item, qty = line['order'], line['item'], line['qty']
        if not line['issued'] or not item or qty <= 0 or source not in delivered:
            continue
        if invoiced[(source, item)] - delivered[source].get(item, 0.0) < qty - QTY_EPS:
            continue
        for picking in linked_pickings.get(line['refid'], []):
            target = picking['order']
            if target == source or target in orders_on_request[line['refid']] or target not in delivered:
                continue
            if (picking['picking'], item) in used or abs(picking['items'].get(item, 0.0) - qty) > QTY_EPS:
                continue
            if invoiced[(target, item)] + qty > delivered[target].get(item, 0.0) + QTY_EPS:
                continue
            moved[line['key']] = (target, picking['picking'])
            used.add((picking['picking'], item))
            invoiced[(source, item)] -= qty
            invoiced[(target, item)] += qty
            break
    return moved
