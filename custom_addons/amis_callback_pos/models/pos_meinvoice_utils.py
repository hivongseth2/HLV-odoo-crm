# -*- coding: utf-8 -*-
"""Hàm thuần dựng dòng hóa đơn meInvoice từ dòng đơn POS (đã quy về số, không đụng ORM).

Mọi số tiền tính bằng đồng (VND, 0 chữ số thập phân) — đúng như Odoo đã làm tròn
price_subtotal / price_subtotal_incl của dòng POS.
"""

from odoo.addons.amis_callback.models.meinvoice_utils import vat_rate_name


def allocate_amount(total, weights):
    """Chia một số tiền nguyên theo tỷ lệ, tổng các phần luôn đúng bằng tổng ban đầu.

    Nhận: total (int, đồng) và weights (list số không âm). Trả: list int cùng độ
    dài weights; phần lẻ do làm tròn dồn cho các dòng có phần dư lớn nhất. Nếu
    0 <= total <= sum(weights) và weights là số nguyên thì không phần nào vượt
    weight của nó. total = 0 → toàn số 0. weights rỗng hoặc tổng bằng 0 mà
    total khác 0 → ValueError.
    """
    total = int(total)
    weight_sum = sum(weights)
    if total == 0:
        return [0] * len(weights)
    if not weights or weight_sum <= 0:
        raise ValueError('Không có dòng nào để phân bổ %s đồng.' % total)

    exact = [total * weight / weight_sum for weight in weights]
    shares = [int(value // 1) for value in exact]
    leftover = total - sum(shares)
    by_remainder = sorted(
        range(len(weights)), key=lambda i: (exact[i] - shares[i], weights[i]), reverse=True,
    )
    for i in by_remainder[:leftover]:
        shares[i] += 1
    return shares


def build_invoice_lines(pos_lines):
    """Dựng giá trị dòng meinvoice.invoice.line từ dòng đơn POS.

    Nhận: list dict, mỗi dict một dòng POS:
        name, code, unit (str), qty (float > 0), vat_rate (float, 8.0 = 8%),
        gross_excl  — tiền trước thuế, TRƯỚC chiết khấu dòng (đồng),
        net_excl    — price_subtotal: trước thuế, SAU chiết khấu dòng (đồng),
        vat         — price_subtotal_incl - price_subtotal (đồng).
    Dòng có net_excl < 0 là dòng giảm giá (giảm giá toàn đơn, thưởng loyalty...).

    Trả: list dict theo field của meinvoice.invoice.line, chỉ gồm dòng hàng. Tiền
    của mỗi dòng giảm giá được chia vào chiết khấu (và tiền thuế) của các dòng hàng
    CÙNG thuế suất, theo tỷ lệ tiền trước thuế — nên tổng hóa đơn bằng đúng tổng
    đơn POS. Không gửi dòng âm lên meInvoice vì dòng hàng âm không hợp lệ trên hóa đơn.

    Lỗi (ValueError, kèm lý do để kế toán đọc): dòng giảm giá có thuế suất mà đơn
    không có dòng hàng nào cùng thuế suất, hoặc giảm nhiều hơn tiền hàng của nhóm đó.
    Không có dòng hàng nào → list rỗng.
    """
    groups = {}
    for index, line in enumerate(pos_lines):
        group = groups.setdefault(float(line['vat_rate']), {'items': [], 'discounts': []})
        key = 'discounts' if line['net_excl'] < 0 else 'items'
        group[key].append(index)

    allocated = {}  # chỉ số dòng hàng → (tiền trước thuế bị trừ, tiền thuế bị trừ)
    for rate, group in groups.items():
        items = [pos_lines[i] for i in group['items']]
        discounts = [pos_lines[i] for i in group['discounts']]
        if not discounts:
            continue
        discount_net = -sum(int(round(d['net_excl'])) for d in discounts)
        discount_vat = -sum(int(round(d['vat'])) for d in discounts)
        weights = [int(round(item['net_excl'])) for item in items]
        if not items or sum(weights) <= 0:
            raise ValueError(
                'Có dòng giảm giá thuế suất %s nhưng không có dòng hàng nào cùng thuế '
                'suất để trừ vào.' % vat_rate_name(rate)
            )
        if discount_net > sum(weights):
            raise ValueError(
                'Giảm giá thuế suất %s (%s đồng) lớn hơn tiền hàng cùng thuế suất (%s đồng).'
                % (vat_rate_name(rate), discount_net, sum(weights))
            )
        net_shares = allocate_amount(discount_net, weights)
        vat_shares = allocate_amount(discount_vat, weights)
        allocated.update(zip(group['items'], zip(net_shares, vat_shares)))

    result = []
    for index, line in enumerate(pos_lines):
        if line['net_excl'] < 0:
            continue
        net_share, vat_share = allocated.get(index, (0, 0))
        qty = float(line['qty'])
        gross = int(round(line['gross_excl']))
        net = int(round(line['net_excl'])) - net_share
        discount = gross - net
        result.append({
            'sort_order': len(result) + 1,
            'item_code': line['code'] or '',
            'item_name': line['name'] or '',
            'unit_name': line['unit'] or '',
            'quantity': qty,
            'unit_price': round(gross / qty, 2) if qty else 0.0,
            'discount_rate': round(discount * 100.0 / gross, 2) if gross else 0.0,
            'discount_amount_oc': discount,
            'amount_oc': gross,
            'amount_without_vat_oc': net,
            'vat_rate_name': vat_rate_name(line['vat_rate']),
            'vat_amount_oc': int(round(line['vat'])) - vat_share,
        })
    return result
