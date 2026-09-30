# -*- coding: utf-8 -*-
"""
check_misa_invoice_gap_pickings.py
==================================
Soát chi tiết TỪNG MẶT HÀNG cho các phiếu khung "Vì sao còn lệch" đang báo — để biết lệch vì
đâu mà xử lý: HĐ nhiều hơn xuất kho, chưa có hóa đơn, có HĐ nhưng thiếu tiền.

Với mỗi phiếu trong PICKING_NAMES, xét theo ĐƠN HÀNG của phiếu (1 đơn có thể giao nhiều phiếu,
xuất HĐ qua nhiều đề nghị):
  A. Odoo : dòng đơn bán (SL đặt/giao, đơn giá trước thuế, % thuế) và mọi phiếu đã xuất của đơn.
  B. MISA : mọi đề nghị nhắc tới mã đơn (đã/chưa phát hành) + dòng hàng của đơn trong đó (SL,
            đơn giá, tiền, % VAT); đề nghị tìm theo TÊN PHIẾU (sale ghi tên phiếu thay mã đơn);
            MỌI dòng HĐ hải quan của đơn (kể cả chưa khớp phiếu) + đã khớp vào phiếu nào.
  C. So từng mã hàng: SL + tiền trước thuế Odoo đã giao vs MISA đã phát hành HĐ (đề nghị + hải
     quan), và % thuế — đánh dấu MISA THỪA SL / THIẾU SL / KHÁC ĐƠN GIÁ / KHÁC % THUẾ / MÃ LẠ.
     KHÁC % THUẾ ở HĐ hải quan hay gặp: khách chế xuất HĐ 0% mà đơn bán Odoo để 8/10%.
  D. Phần MISA thừa: dò phiếu xuất của ĐƠN KHÁC cùng khách có đúng mã hàng + đúng SL thừa — hay
     gặp khi sale ghi nhầm mã đơn trên dòng đề nghị (VD hàng của DH…235474 ghi vào DH…232207).
  E. Phần Odoo chưa có HĐ: dò dòng HĐ hải quan CHƯA KHỚP HẾT có đúng mã hàng nhưng ghi mã đơn
     khác — HĐ hải quan ghi nhầm/thiếu mã đơn thì không bao giờ tự khớp được.

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (đọc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_invoice_gap_pickings.py
"""

from collections import defaultdict

from odoo import fields

# Đơn DH125524949235696 (phiếu 12546, 12874, 13576): có phiếu báo "Đã xuất HĐ" mà tiền HĐ của cả
# đơn = 0 — mục A in từng phiếu của đơn đang ăn theo đề nghị nào, tiền đề nghị dồn cho phiếu nào.
PICKING_NAMES = ['KBC/OUT/12546']
TOLERANCE = 1000.0          # đ — lệch tiền dưới mức này coi như khớp (làm tròn)
CANDIDATE_MONTHS = 6        # dò phiếu đơn khác trong bao nhiêu tháng gần đây

SEP = "=" * 100
SUB = "-" * 100

Picking = env['stock.picking'].sudo()
Move = env['stock.move'].sudo()
CustomsLine = env['misa.invoice.customs.line'].sudo()
misa = env['misa.api.utils'].sudo()
_lines_cache = {}


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def code(value):
    return (value or '').strip().upper()


def request_lines(refid):
    if refid not in _lines_cache:
        _lines_cache[refid] = misa.get_invoice_request_lines(refid)
    return _lines_cache[refid]


def tax_rate(line):
    """% thuế của dòng đơn bán (trước thuế → sau thuế)."""
    return round((line.price_total / line.price_subtotal - 1) * 100, 1) if line.price_subtotal else 0.0


def misa_vat_rate(line):
    amount = line.get('amount_oc') or 0.0
    return round((line.get('vat_amount_oc') or 0.0) / amount * 100, 1) if amount else 0.0


def order_pickings(order):
    return order.misa_invoice_picking_ids.filtered(
        lambda p: p.state == 'done' and p.picking_type_id.code == 'outgoing'
    ).sorted('date_done')


def odoo_shipped_by_item(order):
    """{mã hàng: {qty, amount (trước thuế), rates}} theo move đã xuất của đơn, định giá theo dòng đơn."""
    result = defaultdict(lambda: {'qty': 0.0, 'amount': 0.0, 'rates': set()})
    for picking in order_pickings(order):
        for move in picking.move_ids.filtered(lambda m: m.sale_line_id.order_id == order):
            line = move.sale_line_id
            unit = line.price_subtotal / line.product_uom_qty if line.product_uom_qty else 0.0
            item = result[code(move.product_id.default_code)]
            item['qty'] += move.quantity
            item['amount'] += unit * move.quantity
            item['rates'].add(tax_rate(line))
    return result


def customs_vat_rate(line):
    before = line.amount_before_vat or 0.0
    return round(((line.amount or 0.0) / before - 1) * 100, 1) if before else 0.0


def customs_lines_of(order):
    """Mọi dòng HĐ hải quan của đơn: ghi mã đơn này, gắn đơn này, hoặc đã khớp vào phiếu của đơn."""
    return CustomsLine.search([
        '|', '|', ('order_code', '=', order.name), ('sale_order_id', '=', order.id),
        ('match_ids.picking_id', 'in', order_pickings(order).ids),
    ])


def misa_invoiced_by_item(order_name, requests, customs_lines):
    """{mã hàng: {qty, amount (trước thuế), rates, sources}} đã phát hành HĐ: dòng đề nghị ghi mã
    đơn + TOÀN BỘ dòng HĐ hải quan của đơn (đã xuất HĐ thật dù chưa khớp phiếu)."""
    result = defaultdict(lambda: {'qty': 0.0, 'amount': 0.0, 'rates': set(), 'sources': []})
    for line in customs_lines:
        item = result[code(line.inventory_item_code)]
        item['qty'] += line.quantity or 0.0
        item['amount'] += line.amount_before_vat or 0.0
        item['rates'].add(customs_vat_rate(line))
        item['sources'].append(f"HQ {line.invoice_no}")
    for req in requests:
        if not req['inv_no']:
            continue
        for line in request_lines(req['refid']):
            if (line.get('order_code') or '').strip() != order_name:
                continue
            item = result[code(line.get('inventory_item_code'))]
            item['qty'] += line.get('quantity') or 0.0
            item['amount'] += line.get('amount_oc') or 0.0
            item['rates'].add(misa_vat_rate(line))
            item['sources'].append(req['refno'])
    return result


def candidates_for_extra(order, item_code, extra_qty):
    """Phiếu đã xuất của ĐƠN KHÁC cùng khách, có move đúng mã hàng và đúng SL thừa."""
    since = fields.Datetime.subtract(fields.Datetime.now(), months=CANDIDATE_MONTHS)
    moves = Move.search([
        ('picking_id.picking_type_id.code', '=', 'outgoing'), ('state', '=', 'done'),
        ('date', '>=', since),
        ('product_id.default_code', '=ilike', item_code),
        ('sale_line_id.order_id.partner_id.commercial_partner_id', '=', order.partner_id.commercial_partner_id.id),
        ('sale_line_id.order_id', '!=', order.id),
    ])
    return moves.filtered(lambda m: abs(m.quantity - extra_qty) < 0.001)


def unmatched_customs_for_item(order, item_code):
    """Dòng HĐ hải quan còn chưa khớp hết, đúng mã hàng, ghi mã đơn KHÁC đơn này."""
    since = fields.Date.subtract(fields.Date.today(), months=CANDIDATE_MONTHS)
    return CustomsLine.search([
        ('match_state', 'in', ('pending', 'partial')), ('inventory_item_code', '=ilike', item_code),
        ('order_code', '!=', order.name), '|', ('invoice_date', '=', False), ('invoice_date', '>=', since),
    ])


for name in PICKING_NAMES:
    picking = Picking.search([('name', '=', name)], limit=1)
    print(f"\n{SEP}\n  {name}\n{SEP}")
    if not picking:
        print("  Không tìm thấy phiếu.")
        continue
    gap = (picking.misa_invoice_net_actual_amount or 0.0) - (picking.misa_invoice_allocated_amount or 0.0)
    print(f"  ngày xuất {str(picking.date_done)[:10]} | XK {money(picking.misa_invoice_net_actual_amount)}"
          f" | HĐ quy về {money(picking.misa_invoice_allocated_amount)} | lệch {money(gap)}"
          f" | state={picking.misa_invoice_state} đề nghị={picking.misa_invoice_request_refno or '-'}"
          f" HĐ={picking.misa_invoice_no or '-'}")

    for order in picking.misa_invoice_sale_order_ids:
        print(f"\n  ĐƠN {order.name} — {order.partner_id.commercial_partner_id.name}"
              f" | tổng đơn {money(order.amount_total)} (trước thuế {money(order.amount_untaxed)})")

        print(f"{SUB}\n  A. ODOO — dòng đơn và phiếu đã xuất\n{SUB}")
        for line in order.order_line.filtered(lambda l: not l.display_type):
            unit = line.price_subtotal / line.product_uom_qty if line.product_uom_qty else 0.0
            print(f"    [{line.product_id.default_code or '-'}] đặt {line.product_uom_qty} giao {line.qty_delivered}"
                  f" | giá trước thuế {money(unit)} | thuế {tax_rate(line)}% | sau thuế {money(line.price_total)}")
        for p in order_pickings(order):
            mark = '  ⬅ phiếu đang soát' if p == picking else ''
            master = p.misa_invoice_master_picking_id
            print(f"    phiếu {p.name} {str(p.date_done)[:10]} XK {money(p.misa_invoice_net_actual_amount)}"
                  f" HĐ quy về {money(p.misa_invoice_allocated_amount)} | {p.misa_invoice_state}"
                  f" đề nghị {(master or p).misa_invoice_request_refno or '-'} HĐ {(master or p).misa_invoice_no or '-'}"
                  + (f" | ăn theo {master.name} (đơn {', '.join(master.misa_invoice_sale_order_ids.mapped('name'))},"
                     f" HĐ quy về {money(master.misa_invoice_allocated_amount)})" if master else '')
                  + mark)

        print(f"{SUB}\n  B. MISA — đề nghị nhắc tới {order.name} / {name}, HĐ hải quan\n{SUB}")
        try:
            requests = misa.get_invoice_requests_for_order(order.name)
            by_picking = [r for r in misa.get_invoice_requests_for_order(name) if r['refid'] not in {x['refid'] for x in requests}]
        except Exception as e:
            print(f"    ❌ Lỗi gọi MISA: {e}")
            continue
        for req in requests + by_picking:
            lines = request_lines(req['refid'])
            own = [l for l in lines if (l.get('order_code') or '').strip() == order.name]
            others = sorted({(l.get('order_code') or '').strip() or '(trống)' for l in lines} - {order.name})
            found_by = 'tìm theo tên phiếu' if req in by_picking else 'tìm theo mã đơn'
            print(f"    đề nghị {req['refno']} HĐ {req['inv_no'] or '(chưa phát hành)'} ({found_by})"
                  f" — {len(own)}/{len(lines)} dòng của đơn này" + (f"; đơn khác: {', '.join(others)}" if others else ''))
            for line in own:
                print(f"        [{line.get('inventory_item_code')}] SL {line.get('quantity')}"
                      f" giá {money(line.get('unit_price'))} tiền {money(line.get('amount_oc'))} VAT {misa_vat_rate(line)}%")
            # Dòng KHÔNG ghi mã đơn: Odoo không biết là của đơn nào — hay chính là món đang thiếu.
            for line in (l for l in lines if not (l.get('order_code') or '').strip()):
                print(f"        (không ghi mã đơn) [{line.get('inventory_item_code')}] SL {line.get('quantity')}"
                      f" giá {money(line.get('unit_price'))} tiền {money(line.get('amount_oc'))} VAT {misa_vat_rate(line)}%")
        if not requests and not by_picking:
            print("    MISA không có đề nghị nào ghi mã đơn hoặc tên phiếu này.")
        customs_lines = customs_lines_of(order)
        for line in customs_lines:
            matches = ', '.join(f"{m.picking_id.name} SL {m.quantity:g} = {money(m.amount)}" for m in line.match_ids)
            print(f"    HĐ hải quan {line.invoice_no} ({line.invoice_date or '-'}) mã đơn {line.order_code}"
                  f" [{line.inventory_item_code}] SL {line.quantity:g} | trước thuế {money(line.amount_before_vat)}"
                  f" có VAT {money(line.amount)} (VAT {customs_vat_rate(line)}%) | {line.match_state}"
                  f" khớp {line.matched_qty:g}" + (f" → {matches}" if matches else '')
                  + (f" | {line.match_note}" if line.match_note else ''))

        print(f"{SUB}\n  C. SO TỪNG MÃ HÀNG (Odoo đã xuất vs MISA đã phát hành HĐ, tiền trước thuế)\n{SUB}")
        shipped = odoo_shipped_by_item(order)
        invoiced = misa_invoiced_by_item(order.name, requests, customs_lines)
        extras = []
        missing = []
        for item in sorted(set(shipped) | set(invoiced)):
            s, i = shipped.get(item), invoiced.get(item)
            flags = []
            if not s:
                flags.append('MÃ LẠ (không có trong phiếu đã xuất của đơn)')
            elif not i:
                flags.append('CHƯA CÓ TRÊN HĐ')
            else:
                if i['qty'] > s['qty'] + 0.001:
                    flags.append(f"MISA THỪA SL {i['qty'] - s['qty']:g}")
                elif i['qty'] < s['qty'] - 0.001:
                    flags.append(f"MISA THIẾU SL {s['qty'] - i['qty']:g}")
                elif abs(i['amount'] - s['amount']) > TOLERANCE:
                    flags.append(f"KHÁC ĐƠN GIÁ (lệch {money(i['amount'] - s['amount'])})")
                if s['rates'] != i['rates']:
                    flags.append(f"KHÁC % THUẾ (Odoo {sorted(s['rates'])} / MISA {sorted(i['rates'])})")
            if i and (not s or i['qty'] > s['qty'] + 0.001):
                extras.append((item, i['qty'] - (s['qty'] if s else 0.0)))
            if s and (not i or i['qty'] < s['qty'] - 0.001):
                missing.append((item, s['qty'] - (i['qty'] if i else 0.0)))
            print(f"    [{item}] Odoo SL {s['qty'] if s else 0:g} = {money(s['amount'] if s else 0)}"
                  f" | MISA SL {i['qty'] if i else 0:g} = {money(i['amount'] if i else 0)}"
                  f"{' (' + ', '.join(sorted(set(i['sources']))) + ')' if i else ''}"
                  f"{'   ⚠️ ' + '; '.join(flags) if flags else '   ✓'}")

        if extras:
            print(f"{SUB}\n  D. PHẦN MISA THỪA — có phải hàng của đơn khác cùng khách?\n{SUB}")
            for item, extra_qty in extras:
                found = candidates_for_extra(order, item, extra_qty)
                if not found:
                    print(f"    [{item}] thừa {extra_qty:g}: không thấy phiếu đơn khác có đúng mã + SL này")
                for move in found:
                    other = move.sale_line_id.order_id
                    print(f"    [{item}] thừa {extra_qty:g} ⇄ {move.picking_id.name} ({str(move.date)[:10]}) của đơn"
                          f" {other.name}: HĐ quy về {money(move.picking_id.misa_invoice_allocated_amount)}"
                          f" / XK {money(move.picking_id.misa_invoice_net_actual_amount)}")

        if missing:
            print(f"{SUB}\n  E. PHẦN ODOO CHƯA CÓ HĐ — có HĐ hải quan chưa khớp đúng mã hàng mà ghi mã đơn khác?\n{SUB}")
            for item, short_qty in missing:
                found = unmatched_customs_for_item(order, item)
                if not found:
                    print(f"    [{item}] thiếu {short_qty:g}: không có HĐ hải quan chưa khớp nào cùng mã hàng")
                for line in found:
                    print(f"    [{item}] thiếu {short_qty:g} ⇄ HĐ hải quan {line.invoice_no} ({line.invoice_date or '-'})"
                          f" mã đơn {line.order_code} khách {line.partner_name or '-'} SL {line.quantity:g}"
                          f" còn chưa khớp {line.remaining_qty():g} | {line.match_note or line.match_state}")

print(f"\n{SEP}")
print("  Đọc kết quả:\n"
      "    MISA THỪA SL + mục D thấy phiếu đơn khác  → sale ghi nhầm mã đơn trên dòng đề nghị.\n"
      "    KHÁC ĐƠN GIÁ / KHÁC % THUẾ                → giá hoặc thuế trên đơn bán Odoo khác hóa đơn.\n"
      "    Mục E thấy HĐ hải quan ghi mã đơn khác      → HĐ hải quan ghi nhầm mã đơn, khớp tay trên tab Đơn hải quan.\n"
      "    CHƯA CÓ TRÊN HĐ + không có đề nghị nào   → chưa lập đề nghị / chưa xuất HĐ thật.\n"
      "    Đề nghị 'tìm theo tên phiếu' ghi mã đơn khác → HĐ có nhưng ghi sai/thiếu mã đơn.")
print(SEP)
