"""Hàm thuần tìm dòng đề nghị xuất HĐ bị sale ghi nhầm / bỏ trống mã đơn — không đụng env/ORM."""

from collections import defaultdict

QTY_EPS = 0.001


def item_key(code):
    """Mã hàng chuẩn hóa để so Odoo với MISA: bỏ khoảng trắng 2 đầu, viết hoa. None/False → ''."""
    return (code or '').strip().upper()


def name_key(name):
    """Tên hàng chuẩn hóa để so tên trên HĐ MISA với tên sản phẩm Odoo: gộp khoảng trắng, không
    phân biệt hoa/thường. None/False → ''."""
    return ' '.join((name or '').split()).casefold()


def owned_qty(order_name, line_order, line_qty, moves):
    """SL của 1 dòng đề nghị tính cho đơn order_name sau khi chuyển dòng ghi nhầm.

    Nhận: line_order = mã đơn ghi trên dòng ('' nếu bỏ trống), line_qty = SL dòng, moves = phần đã
    chuyển của dòng này [(mã đơn nhận, phiếu, SL)] (kết quả find_mislabeled_lines, [] nếu không).
    Trả: dòng ghi order_name giữ SL trừ phần đã chuyển đi; cộng phần chuyển đến order_name.
    Dòng không liên quan → 0.
    """
    own = line_qty - sum(qty for _target, _picking, qty in moves) if line_order == order_name else 0.0
    return own + sum(qty for target, _picking, qty in moves if target == order_name)


def find_mislabeled_lines(lines, delivered, linked_pickings):
    """Phần dòng đề nghị ĐÃ phát hành HĐ thật ra là hàng của phiếu P thuộc đơn Y, dù dòng ghi mã
    đơn X khác hoặc bỏ trống mã đơn. Case thật: đề nghị KBC/OUT/09323 ghi QHTIG308 ×5 + TEFLON
    3mm ×1 của KBC/OUT/12296 (DH…235474) vào DH…232207; đề nghị KBC/OUT/11810 ghi 1 dòng UT6581
    SL 2 cho DH…234991, 1 cái là của KBC/OUT/11375 (DH…234488).

    Nhận:
      lines: list dict {key, refid, order, item, qty, issued} — MỌI dòng của các đề nghị đang xét,
        gồm cả đề nghị của đơn X, Y (order = mã đơn ghi trên dòng, '' nếu bỏ trống; item =
        item_key(mã hàng)).
      delivered: {mã đơn: {item: SL đã giao}} theo dòng đơn bán Odoo. Đơn không có trong đây coi
        như không biết — không chuyển gì đi hay đến đơn đó.
      linked_pickings: {refid: [{picking, order, items: {item: SL xuất}}]} — phiếu xuất kho thuộc
        ĐÚNG 1 đơn đang gắn vào đề nghị refid.

    Chuyển SL q = SL mã i của phiếu P, từ dòng L (đề nghị R, mã i) sang đơn Y khi:
      1. P thuộc đơn Y, gắn vào R. Dòng ghi mã X ≠ Y thì thêm: R không có dòng nào ghi mã Y CÙNG
         mã hàng i — sale đã ghi đúng mã Y cho mã hàng đó thì dòng ghi X nhiều khả năng đúng là
         của X. Chỉ xét cùng mã hàng: 1 đề nghị hay ghi đúng mã đơn cho vài món và ghi nhầm vài
         món khác (case thật đề nghị KBC/OUT/12907: EP118, DUNGMOI ghi đúng DH…235871, còn 2F4
         45m 2li ×50, CLAN10 ×5, CQ100 ×5 của KBC/OUT/12579 lại ghi DH…235869).
      2. Dòng còn đủ SL: SL dòng (trừ phần đã chuyển) ≥ q. Được tách 1 phần dòng.
      3. Dòng ghi mã X: X đang thừa HĐ mã i ít nhất q (SL đã phát hành HĐ ghi X − SL X đã giao ≥ q),
         bỏ phần này đi X không bị thiếu. Dòng bỏ trống mã đơn: không cần điều kiện này.
      4. Y chưa đủ HĐ mã i (SL đã phát hành HĐ ghi Y + q ≤ SL Y đã giao): không đẩy Y thành thừa.
    Mỗi phiếu nhận mỗi mã hàng tối đa 1 lần. Xét dòng theo thứ tự key để kết quả luôn như nhau.

    Trả {key dòng: [(mã đơn Y, tên phiếu P, SL chuyển), ...]}; không có gì → {}.
    """
    invoiced = defaultdict(float)
    coded_on_request = defaultdict(set)     # refid -> {(mã đơn, mã hàng)} ghi trên đề nghị
    for line in lines:
        coded_on_request[line['refid']].add((line['order'], line['item']))
        if line['issued'] and line['order']:
            invoiced[(line['order'], line['item'])] += line['qty']

    moved = defaultdict(list)
    used = set()
    for line in sorted(lines, key=lambda l: str(l['key'])):
        source, item = line['order'], line['item']
        if not line['issued'] or not item or line['qty'] <= 0 or (source and source not in delivered):
            continue
        remaining = line['qty']
        for picking in linked_pickings.get(line['refid'], []):
            target = picking['order']
            qty = picking['items'].get(item, 0.0)
            if target == source or target not in delivered or qty <= 0 or (picking['picking'], item) in used:
                continue
            if source and (target, item) in coded_on_request[line['refid']]:
                continue
            if remaining < qty - QTY_EPS:
                continue
            if source and invoiced[(source, item)] - delivered[source].get(item, 0.0) < qty - QTY_EPS:
                continue
            if invoiced[(target, item)] + qty > delivered[target].get(item, 0.0) + QTY_EPS:
                continue
            moved[line['key']].append((target, picking['picking'], qty))
            used.add((picking['picking'], item))
            remaining -= qty
            if source:
                invoiced[(source, item)] -= qty
            invoiced[(target, item)] += qty
    return dict(moved)
