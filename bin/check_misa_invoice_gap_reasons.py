# -*- coding: utf-8 -*-
"""
check_misa_invoice_gap_reasons.py
=================================
Mọi phiếu đang lệch trong khung "Vì sao còn lệch" (lọc được theo sale / tháng xuất kho) — gom
theo ĐƠN, mỗi đơn in gọn LÝ DO và NÊN LÀM GÌ, không phải soát tay từng phiếu. Muốn xem chi tiết
đủ A–E của 1 phiếu thì dùng bin/check_misa_invoice_gap_pickings.py.

Mỗi đơn:
  - tiền HĐ theo đơn ĐANG LƯU vs tính lại NGAY từ MISA (dùng đúng cách module tính, có chuyển dòng
    ghi nhầm / bỏ trống mã đơn — sale.order._misa_invoice_line_moves / _owned_request_amounts);
  - so từng mã hàng: Odoo đã giao (dòng đơn bán) vs đã phát hành HĐ (đề nghị + HĐ hải quan);
  - kết luận: chưa xuất HĐ / đề nghị chưa phát hành / HĐ thiếu mã / HĐ thừa mã / sai % thuế /
    có dòng ghi nhầm mã đơn / số theo đơn đang lưu đã cũ.
Cuối cùng in danh sách đơn mà SOÁT LẠI THEO ĐƠN là tự hết lệch — dán vào ORDERS của
bin/fix_misa_invoice_reassign_orders.py rồi chạy.

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (đọc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_invoice_gap_reasons.py
"""

from collections import defaultdict

from odoo.addons.misa_invoice_status_report.models.misa_invoice_reassign_utils import item_key, owned_qty

SALER_CODE = False          # False = mọi sale; hoặc 'TRANTHIMYDUYEN'
MONTH = False               # False = mọi tháng; hoặc '2026-08' (tháng xuất kho của phiếu lệch)
ONLY_ORDERS = []            # để trống = tự lấy theo 2 lọc trên; hoặc ['DH125524949235869', ...]
TOLERANCE = 1000.0          # đ
MAX_ORDERS = 100            # đơn lệch nhiều nhất trước
SEP = "=" * 100

Picking = env['stock.picking'].sudo()
SaleOrder = env['sale.order'].sudo()
CustomsLine = env['misa.invoice.customs.line'].sudo()
if not hasattr(SaleOrder, '_misa_invoice_owned_request_amounts'):
    raise SystemExit("❌ Server chưa có bản chuyển dòng ghi nhầm mã đơn (models/misa_invoice_line_reassign.py).")


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def picking_gap(picking):
    return (picking.misa_invoice_net_actual_amount or 0.0) - (picking.misa_invoice_allocated_amount or 0.0)


def tax_rate(before, after):
    return round((after / before - 1) * 100, 1) if before else 0.0


def gap_orders():
    """[(đơn, [phiếu lệch])] — đơn lệch nhiều nhất trước."""
    if ONLY_ORDERS:
        orders = SaleOrder.search([('name', 'in', ONLY_ORDERS)])
        return [(o, o._misa_invoice_done_out_pickings().filtered(lambda p: abs(picking_gap(p)) > TOLERANCE)) for o in orders]
    domain = Picking._misa_invoice_dashboard_base_domain()
    if SALER_CODE:
        domain += [('misa_invoice_saler_code', '=', SALER_CODE)]
    by_order = defaultdict(lambda: Picking.browse())
    for picking in Picking.search(domain):
        if abs(picking_gap(picking)) <= TOLERANCE:
            continue
        if MONTH and (not picking.date_done or picking.date_done.strftime('%Y-%m') != MONTH):
            continue
        for order in picking.misa_invoice_sale_order_ids:
            by_order[order.id] |= picking
    rows = [(SaleOrder.browse(oid), pickings) for oid, pickings in by_order.items()]
    rows.sort(key=lambda r: -abs(sum(picking_gap(p) for p in r[0]._misa_invoice_done_out_pickings())))
    return rows[:MAX_ORDERS]


def shipped_by_item(order):
    """{mã hàng: {qty, amount trước thuế, rates}} — theo dòng đơn bán (qty_delivered, đã trừ trả)."""
    result = defaultdict(lambda: {'qty': 0.0, 'amount': 0.0, 'rates': set()})
    for line in order.order_line.filtered(lambda l: not l.display_type and l.qty_delivered):
        item = result[item_key(line.product_id.default_code)]
        unit = line.price_subtotal / line.product_uom_qty if line.product_uom_qty else 0.0
        item['qty'] += line.qty_delivered
        item['amount'] += unit * line.qty_delivered
        item['rates'].add(tax_rate(line.price_subtotal, line.price_total))
    return result


def invoiced_by_item(order, moves, lines):
    """{mã hàng: {qty, amount trước thuế, rates}} đã phát hành HĐ, sau khi chuyển dòng ghi nhầm."""
    result = defaultdict(lambda: {'qty': 0.0, 'amount': 0.0, 'rates': set()})
    for key, (req, raw) in lines.items():
        if not req['inv_no']:
            continue
        line_qty = raw.get('quantity') or 0.0
        qty = owned_qty(order.name, (raw.get('order_code') or '').strip(), line_qty, moves.get(key, []))
        if qty <= 0:
            continue
        item = result[item_key(raw.get('inventory_item_code'))]
        before = raw.get('amount_oc') or 0.0
        item['qty'] += qty
        item['amount'] += before * qty / line_qty if line_qty else before
        item['rates'].add(tax_rate(before, before + (raw.get('vat_amount_oc') or 0.0)))
    customs = CustomsLine.search([
        '|', '|', ('order_code', '=', order.name), ('sale_order_id', '=', order.id),
        ('match_ids.picking_id', 'in', order._misa_invoice_done_out_pickings().ids),
    ])
    for line in customs:
        item = result[item_key(line.inventory_item_code)]
        item['qty'] += line.quantity or 0.0
        item['amount'] += line.amount_before_vat or 0.0
        item['rates'].add(tax_rate(line.amount_before_vat or 0.0, line.amount or 0.0))
    return result, customs


rows = gap_orders()
print(f"\n{SEP}\n  VÌ SAO CÒN LỆCH — {len(rows)} đơn"
      f"{' | sale ' + SALER_CODE if SALER_CODE else ''}{' | tháng ' + MONTH if MONTH else ''}\n{SEP}")

requests_cache, lines_cache = {}, {}
refresh_fixes = []
reason_count = defaultdict(int)
for order, gap_pickings in rows:
    order_gap = sum(picking_gap(p) for p in order._misa_invoice_done_out_pickings())
    print(f"\n  {order.name} — {order.partner_id.commercial_partner_id.name} | lệch cả đơn {money(order_gap)}"
          f" | phiếu lệch: {', '.join(f'{p.name} ({money(picking_gap(p))})' for p in gap_pickings)}")
    try:
        moves, lines = order._misa_invoice_line_moves(requests_cache, lines_cache)
        owned = order._misa_invoice_owned_request_amounts(moves, lines)
    except Exception as e:
        print(f"      ❌ lỗi gọi MISA: {e}")
        continue
    issued_now = sum(amount for req, amount, _n in owned if req['inv_no'])
    pending = [(req['refno'], amount) for req, amount, _n in owned if not req['inv_no']]
    shipped = shipped_by_item(order)
    invoiced, customs = invoiced_by_item(order, moves, lines)

    reasons = []
    for req, amount, notes in owned:
        state = f"HĐ {req['inv_no']}" if req['inv_no'] else 'chưa phát hành'
        print(f"      đề nghị {req['refno']} {state}: {money(amount)}" + (f" — {'; '.join(notes)}" if notes else ''))
    for line in customs:
        print(f"      HĐ hải quan {line.invoice_no} [{line.inventory_item_code}] SL {line.quantity:g} {money(line.amount)} ({line.match_state})")
    if not owned and not customs:
        print("      MISA không có đề nghị / HĐ hải quan nào cho đơn này")

    missing, extra, tax_diff, price_diff = [], [], [], []
    for item in sorted(set(shipped) | set(invoiced)):
        s, i = shipped.get(item), invoiced.get(item)
        s_qty, i_qty = (s['qty'] if s else 0.0), (i['qty'] if i else 0.0)
        if i_qty < s_qty - 0.001:
            missing.append(f"[{item}] {s_qty - i_qty:g}")
        elif i_qty > s_qty + 0.001:
            extra.append(f"[{item}] {i_qty - s_qty:g}")
        elif s and i and abs(i['amount'] - s['amount']) > TOLERANCE:
            price_diff.append(f"[{item}] {money(i['amount'] - s['amount'])}")
        if s and i and s['rates'] != i['rates']:
            tax_diff.append(f"[{item}] Odoo {sorted(s['rates'])}% / HĐ {sorted(i['rates'])}%")

    stale = bool(order.misa_invoice_order_checked_at) and abs(order.misa_invoice_order_invoiced_amount - issued_now) > TOLERANCE
    has_moves = any(order.name in {(lines[k][1].get('order_code') or '').strip()} | {t for t, _p, _q in v}
                    for k, v in moves.items())
    if not issued_now and not customs:
        reasons.append('CHƯA XUẤT HĐ' + (f" — đề nghị chưa phát hành: {', '.join(f'{r} ({money(a)})' for r, a in pending)}" if pending else ''))
    if missing and (issued_now or customs):
        reasons.append(f"HĐ THIẾU MÃ: {', '.join(missing)}")
    if extra:
        reasons.append(f"HĐ THỪA MÃ: {', '.join(extra)} (xuất HĐ trùng, hàng trả chưa điều chỉnh HĐ, hoặc dòng ghi nhầm mã đơn chưa đủ điều kiện chuyển)")
    if tax_diff:
        reasons.append(f"SAI % THUẾ: {', '.join(tax_diff)} → sửa thuế trên đơn bán")
    if price_diff:
        reasons.append(f"KHÁC ĐƠN GIÁ: {', '.join(price_diff)}")
    if has_moves:
        reasons.append('CÓ DÒNG GHI NHẦM / BỎ TRỐNG MÃ ĐƠN → soát lại theo đơn sẽ tự chuyển')
    if stale:
        reasons.append(f"SỐ THEO ĐƠN ĐANG LƯU CŨ: {money(order.misa_invoice_order_invoiced_amount)} → MISA hiện {money(issued_now)}"
                       " → soát lại theo đơn")
    if not order.misa_invoice_order_checked_at and (has_moves or issued_now):
        reasons.append('ĐƠN CHƯA SOÁT THEO ĐƠN (đang tính theo phiếu) → soát lại theo đơn')
    if not reasons:
        reasons.append('Mặt hàng khớp, số theo đơn mới — lệch do chia tiền giữa các phiếu / đơn gộp, xem bằng check_misa_invoice_gap_pickings.py')
    for reason in reasons:
        print(f"      ⇒ {reason}")
        reason_count[reason.split(':')[0].split(' →')[0].split(' —')[0]] += 1
    if has_moves or stale or (not order.misa_invoice_order_checked_at and issued_now):
        refresh_fixes.append(order.name)

print(f"\n{SEP}\n  TỔNG HỢP LÝ DO")
for reason, count in sorted(reason_count.items(), key=lambda kv: -kv[1]):
    print(f"    {count:>4} đơn — {reason}")
print(f"\n  {len(refresh_fixes)} đơn SOÁT LẠI THEO ĐƠN là tự sửa — dán vào ORDERS của bin/fix_misa_invoice_reassign_orders.py:")
print(f"    ORDERS = {refresh_fixes!r}")
print(SEP)
