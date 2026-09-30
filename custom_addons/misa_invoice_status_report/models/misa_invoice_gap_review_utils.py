"""Hàm thuần xếp lý do lệch của 1 đơn cho báo cáo đối soát hằng ngày — không đụng env/ORM."""

from collections import defaultdict

QTY_EPS = 0.001


def tax_rate(before, after):
    """% thuế (làm tròn 0,1) từ tiền trước / sau thuế. Trước thuế 0 → 0."""
    return round((after / before - 1) * 100, 1) if before else 0.0


def compare_items(shipped, invoiced, tolerance):
    """So từng mã hàng Odoo đã giao với đã phát hành HĐ.

    Nhận: shipped / invoiced = {mã hàng: {qty, amount (trước thuế), rates: set % thuế}};
    tolerance = dung sai tiền (đ).
    Trả dict 4 list chuỗi đọc được: missing ("[mã] SL thiếu"), extra ("[mã] SL thừa"),
    price_diff ("[mã] tiền lệch" khi cùng SL mà tiền khác quá dung sai), tax_diff ("[mã] Odoo
    [..]% / HĐ [..]%"). Mã chỉ có 1 bên vẫn so (bên kia SL 0). Không lệch gì → 4 list rỗng.
    """
    result = {'missing': [], 'extra': [], 'price_diff': [], 'tax_diff': []}
    for item in sorted(set(shipped) | set(invoiced)):
        s, i = shipped.get(item), invoiced.get(item)
        s_qty, i_qty = (s['qty'] if s else 0.0), (i['qty'] if i else 0.0)
        if i_qty < s_qty - QTY_EPS:
            result['missing'].append('[%s] %g' % (item, s_qty - i_qty))
        elif i_qty > s_qty + QTY_EPS:
            result['extra'].append('[%s] %g' % (item, i_qty - s_qty))
        elif s and i and abs(i['amount'] - s['amount']) > tolerance:
            result['price_diff'].append('[%s] %.0f' % (item, i['amount'] - s['amount']))
        if s and i and s['rates'] != i['rates']:
            result['tax_diff'].append('[%s] Odoo %s%% / HĐ %s%%' % (item, sorted(s['rates']), sorted(i['rates'])))
    return result


def duplicate_requests(owned):
    """Nhóm đề nghị trùng: >= 2 đề nghị cùng tính cho 1 đơn đúng 1 số tiền (làm tròn đồng) —
    sale lập lại đề nghị thay vì sửa cái cũ (case thật DH…237065: TSN/OUT/14643 đã phát hành +
    TSN/OUT/14619 chưa phát hành, cùng 5.248.800 đ).

    Nhận: owned = [(refno, inv_no hoặc '', tiền)]. Trả [(tiền, [(refno, inv_no), ...])] chỉ các
    nhóm >= 2 đề nghị; không có → [].
    """
    groups = defaultdict(list)
    for refno, inv_no, amount in owned:
        groups[round(amount)].append((refno, inv_no))
    return [(amount, reqs) for amount, reqs in groups.items() if len(reqs) > 1]


def opposite_pairs(entries, tolerance):
    """Cặp đơn cùng khách lệch ngược dấu đúng 1 số tiền — hàng của đơn thiếu nằm trên HĐ của đơn
    thừa (case thật DH…234115 +1.555.200 / DH…236901 −1.555.200).

    Nhận: entries = [(khóa khách, mã đơn, lệch)]; lệch dương = thiếu HĐ, âm = thừa HĐ.
    Trả [(đơn thiếu, đơn thừa, số tiền)]; mỗi đơn vào tối đa 1 cặp; không có → [].
    """
    by_partner = defaultdict(list)
    for partner, order, gap in entries:
        by_partner[partner].append((order, gap))
    pairs, used = [], set()
    for rows in by_partner.values():
        for short, short_gap in rows:
            if short_gap <= tolerance or short in used:
                continue
            for over, over_gap in rows:
                if over_gap >= -tolerance or over in used or abs(short_gap + over_gap) > tolerance:
                    continue
                pairs.append((short, over, short_gap))
                used |= {short, over}
                break
    return pairs
