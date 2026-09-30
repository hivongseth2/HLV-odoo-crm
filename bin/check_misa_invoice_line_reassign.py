# -*- coding: utf-8 -*-
"""
check_misa_invoice_line_reassign.py
===================================
Chạy THỬ quy tắc "dòng đề nghị ghi nhầm mã đơn" (find_mislabeled_lines trong
models/misa_invoice_reassign_utils.py) trên dữ liệu thật — KHÔNG ghi gì — để xem trước mọi dòng
sẽ được chuyển sang đơn khác trước khi đưa vào cách tính HĐ theo đơn của module.

Vì sao: sale ghi nhầm mã đơn trên dòng đề nghị thì 1 dòng HĐ bị tính 2 lần — cho đơn ghi trên
dòng (soát theo mã đơn) và cho đơn thật (phiếu của nó đang gắn vào đề nghị đó). Case thật:
KBC/OUT/09356 thừa 4.984.200 đ (hàng của KBC/OUT/12296), KBC/OUT/11810 thừa 1.134.000 đ (hàng
của KBC/OUT/11375).

Cách soát: lấy các đơn X đang có phiếu HĐ NHIỀU HƠN xuất kho → mọi đề nghị ghi mã X trên MISA
→ phiếu của đơn KHÁC đang gắn vào các đề nghị đó (đơn Y) → mọi đề nghị ghi mã Y → chạy
find_mislabeled_lines. In từng dòng sẽ chuyển, và đơn X nào đang thừa mà không tìm ra lý do.

Cần file models/misa_invoice_reassign_utils.py đã có trên server (git pull là đủ — file thuần,
chưa nơi nào trong module dùng, không cần nâng cấp module).

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (đọc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_invoice_line_reassign.py
"""

from collections import defaultdict

try:
    from odoo.addons.misa_invoice_status_report.models.misa_invoice_reassign_utils import (
        find_mislabeled_lines, item_key,
    )
except ImportError:
    raise SystemExit("❌ Chưa có models/misa_invoice_reassign_utils.py trên server — git pull trước.")

ONLY_ORDERS = []            # để trống = mọi đơn đang thừa HĐ; hoặc ['DH125524949232207', ...]
TOLERANCE = 1000.0          # đ
SEP = "=" * 100

Picking = env['stock.picking'].sudo()
SaleOrder = env['sale.order'].sudo()
misa = env['misa.api.utils'].sudo()
requests_cache = {}         # mã đơn -> [{refno, refid, inv_no}]
lines_cache = {}            # refid -> dòng đề nghị


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def requests_of(order_name):
    if order_name not in requests_cache:
        requests_cache[order_name] = misa.get_invoice_requests_for_order(order_name)
    return requests_cache[order_name]


def lines_of(refid):
    if refid not in lines_cache:
        lines_cache[refid] = misa.get_invoice_request_lines(refid)
    return lines_cache[refid]


def line_amount(line):
    return (line.get('amount_oc') or 0.0) + (line.get('vat_amount_oc') or 0.0) - (line.get('discount_amount_oc') or 0.0)


def done_outgoing(pickings):
    return pickings.filtered(lambda p: p.state == 'done' and p.picking_type_id.code == 'outgoing')


def delivered_by_item(order):
    result = defaultdict(float)
    for line in order.order_line.filtered(lambda l: not l.display_type):
        result[item_key(line.product_id.default_code)] += line.qty_delivered
    return dict(result)


def picking_items(picking):
    result = defaultdict(float)
    for move in picking.move_ids.filtered(lambda m: m.state == 'done'):
        result[item_key(move.product_id.default_code)] += move.quantity
    return dict(result)


def linked_pickings_for(refids):
    """{refid: [{picking, order, items}]} — phiếu 1 đơn gắn vào đề nghị (chính nó hoặc phiếu nó ăn theo)."""
    result = defaultdict(list)
    pickings = done_outgoing(Picking.search([
        '|', ('misa_invoice_request_refid', 'in', list(refids)),
        ('misa_invoice_master_picking_id.misa_invoice_request_refid', 'in', list(refids)),
    ]))
    for picking in pickings:
        if len(picking.misa_invoice_sale_order_ids) != 1:
            continue
        refid = picking.misa_invoice_request_refid or picking.misa_invoice_master_picking_id.misa_invoice_request_refid
        result[refid].append({
            'picking': picking.name, 'order': picking.misa_invoice_sale_order_ids.name, 'items': picking_items(picking),
        })
    return result


def over_invoiced_orders():
    domain = Picking._misa_invoice_dashboard_base_domain()
    if ONLY_ORDERS:
        domain += [('misa_invoice_sale_order_ids.name', 'in', ONLY_ORDERS)]
    orders = SaleOrder.browse()
    for picking in Picking.search(domain):
        gap = (picking.misa_invoice_net_actual_amount or 0.0) - (picking.misa_invoice_allocated_amount or 0.0)
        if gap < -TOLERANCE:
            orders |= picking.misa_invoice_sale_order_ids
    return orders


def order_gap(order):
    pickings = done_outgoing(order.misa_invoice_picking_ids)
    return sum((p.misa_invoice_net_actual_amount or 0.0) - (p.misa_invoice_allocated_amount or 0.0) for p in pickings)


candidates = over_invoiced_orders()
print(f"\n{SEP}\n  DÒNG ĐỀ NGHỊ GHI NHẦM MÃ ĐƠN — CHẠY THỬ trên {len(candidates)} đơn đang thừa HĐ\n{SEP}")

total_moved = 0.0
unexplained = []
for order in candidates:
    try:
        own_requests = [r for r in requests_of(order.name) if r['inv_no']]
        linked = linked_pickings_for({r['refid'] for r in own_requests})
        targets = {p['order'] for plist in linked.values() for p in plist} - {order.name}
        target_orders = SaleOrder.search([('name', 'in', list(targets))])
        all_requests = {r['refid']: r for r in own_requests}
        for target in target_orders:
            for req in requests_of(target.name):
                all_requests.setdefault(req['refid'], req)
        lines, by_key = [], {}
        for refid, req in all_requests.items():
            for idx, raw in enumerate(lines_of(refid)):
                line = {
                    'key': (refid, idx), 'refid': refid, 'order': (raw.get('order_code') or '').strip(),
                    'item': item_key(raw.get('inventory_item_code')), 'qty': raw.get('quantity') or 0.0,
                    'issued': bool(req['inv_no']),
                }
                lines.append(line)
                by_key[line['key']] = (req, raw)
    except Exception as e:
        print(f"\n  ❌ {order.name}: lỗi gọi MISA — {e}")
        continue
    delivered = {o.name: delivered_by_item(o) for o in order | target_orders}
    moved = find_mislabeled_lines(lines, delivered, linked)
    moved_from_here = {k: v for k, v in moved.items() if (by_key[k][1].get('order_code') or '').strip() == order.name}

    gap = order_gap(order)
    moved_amount = sum(line_amount(by_key[k][1]) for k in moved_from_here)
    total_moved += moved_amount
    print(f"\n  {order.name} — {order.partner_id.commercial_partner_id.name}"
          f" | đang lệch {money(gap)} (âm = HĐ thừa) | chuyển đi {money(moved_amount)} → còn lệch {money(gap + moved_amount)}")
    if not moved_from_here:
        unexplained.append((order, gap))
        print("      (không có dòng nào đủ điều kiện chuyển — thừa vì lý do khác)")
    for key, (target, picking_name) in sorted(moved_from_here.items(), key=lambda kv: str(kv[0])):
        req, raw = by_key[key]
        target_order = target_orders.filtered(lambda o, t=target: o.name == t)
        print(f"      đề nghị {req['refno']} HĐ {req['inv_no']}: [{raw.get('inventory_item_code')}] SL {raw.get('quantity'):g}"
              f" {money(line_amount(raw))} đ → {target} (phiếu {picking_name}; đơn đó đang lệch {money(order_gap(target_order))})")

print(f"\n{SEP}")
print(f"  Tổng tiền HĐ sẽ chuyển sang đúng đơn: {money(total_moved)} đ. {len(unexplained)} đơn thừa HĐ không do ghi nhầm mã đơn.")
print("  Đơn nhận ('đơn đó đang lệch'): 0 = đang được tính HĐ qua đề nghị gắn vào phiếu → hết đếm 2 lần;\n"
      "  > 0 = đang báo thiếu đúng khoản này → sau khi chuyển sẽ hết thiếu.")
print(SEP)
