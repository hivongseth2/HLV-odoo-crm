# -*- coding: utf-8 -*-
"""
check_misa_invoice_line_reassign.py
===================================
Chạy THỬ quy tắc "dòng đề nghị ghi nhầm / bỏ trống mã đơn" trên dữ liệu thật — KHÔNG ghi gì —
để xem trước mọi phần dòng sẽ được tính sang đơn khác trước khi đưa vào cách tính HĐ theo đơn.
Dùng ĐÚNG method của module (sale.order._misa_invoice_line_moves → find_mislabeled_lines trong
models/misa_invoice_reassign_utils.py), nên chạy thử ra gì thì chạy thật ra đúng như vậy.

Vì sao: soát HĐ theo đơn chỉ cộng dòng ghi đúng mã đơn, còn phiếu chưa soát theo đơn tính HĐ
qua đề nghị gắn vào nó. Case thật:
  - ghi nhầm mã đơn → đếm 2 lần: KBC/OUT/09356 thừa 4.984.200 đ (hàng của KBC/OUT/12296);
    KBC/OUT/11810 thừa 1.134.000 đ (1 dòng UT6581 SL 2, 1 cái là của KBC/OUT/11375);
  - dòng bỏ trống mã đơn → soát theo đơn ra 0: DH…235029 (KBC/OUT/13489 đã có HĐ 8.726.400 đ).

Soát 2 chiều: đơn có phiếu HĐ NHIỀU HƠN xuất kho (đơn X, dòng bị ghi vào), và đơn có phiếu đã
báo "Đã xuất HĐ" mà tiền HĐ quy về vẫn THIẾU (đơn Y, dòng đáng ra là của nó).

Cần module có models/misa_invoice_line_reassign.py trên server (git pull + khởi động lại Odoo —
chỉ thêm method, chưa nơi nào gọi, không đổi cách tính gì).

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (đọc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_invoice_line_reassign.py
"""

ONLY_ORDERS = []            # để trống = tự tìm theo 2 chiều ở trên; hoặc ['DH125524949235029', ...]
TOLERANCE = 1000.0          # đ
UNEXPLAINED_TOP = 10        # in bấy nhiêu đơn lệch lớn nhất không do dòng ghi nhầm
SEP = "=" * 100

Picking = env['stock.picking'].sudo()
SaleOrder = env['sale.order'].sudo()
if not hasattr(SaleOrder, '_misa_invoice_line_moves'):
    raise SystemExit("❌ Server chưa có models/misa_invoice_line_reassign.py — git pull + khởi động lại Odoo trước.")


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def line_amount(line):
    return (line.get('amount_oc') or 0.0) + (line.get('vat_amount_oc') or 0.0) - (line.get('discount_amount_oc') or 0.0)


def picking_gap(picking):
    return (picking.misa_invoice_net_actual_amount or 0.0) - (picking.misa_invoice_allocated_amount or 0.0)


def order_gap(order):
    return sum(picking_gap(p) for p in order._misa_invoice_done_out_pickings())


def seed_orders():
    if ONLY_ORDERS:
        return SaleOrder.search([('name', 'in', ONLY_ORDERS)])
    orders = SaleOrder.browse()
    for picking in Picking.search(Picking._misa_invoice_dashboard_base_domain()):
        gap = picking_gap(picking)
        if gap < -TOLERANCE or (gap > TOLERANCE and picking.misa_invoice_state == 'invoiced'):
            orders |= picking.misa_invoice_sale_order_ids
    return orders


seeds = seed_orders()
print(f"\n{SEP}\n  DÒNG ĐỀ NGHỊ GHI NHẦM / BỎ TRỐNG MÃ ĐƠN — CHẠY THỬ trên {len(seeds)} đơn\n{SEP}")

requests_cache, lines_cache = {}, {}
seen = set()
total_moved = 0.0
unexplained = []
for order in seeds:
    try:
        moves, lines = order._misa_invoice_line_moves(requests_cache, lines_cache)
    except Exception as e:
        print(f"\n  ❌ {order.name}: lỗi gọi MISA — {e}")
        continue
    rows = []
    for key, targets in moves.items():
        req, raw = lines[key]
        source = (raw.get('order_code') or '').strip()
        for target, picking_name, qty in targets:
            if order.name not in (source, target) or (key, target, picking_name) in seen:
                continue
            seen.add((key, target, picking_name))
            line_qty = raw.get('quantity') or 0.0
            amount = line_amount(raw) * qty / line_qty if line_qty else 0.0
            rows.append((req, raw, source, target, picking_name, qty, amount))
    if not rows:
        unexplained.append((order, order_gap(order)))
        continue
    print(f"\n  {order.name} — {order.partner_id.commercial_partner_id.name} | đang lệch {money(order_gap(order))}")
    for req, raw, source, target, picking_name, qty, amount in rows:
        total_moved += amount
        target_order = SaleOrder.search([('name', '=', target)], limit=1)
        print(f"      đề nghị {req['refno']} HĐ {req['inv_no']}: [{raw.get('inventory_item_code')}]"
              f" SL {qty:g}/{(raw.get('quantity') or 0):g} = {money(amount)} đ"
              f" | ghi mã {source or '(trống)'} → {target} (phiếu {picking_name}, đơn đó đang lệch {money(order_gap(target_order))})")

print(f"\n{SEP}")
print(f"  {len(seen)} phần dòng sẽ tính sang đúng đơn, tổng {money(total_moved)} đ.")
print("  Đọc: đơn ghi mã đang lệch âm (thừa) → hết thừa; đơn nhận đang lệch 0 = đang được tính qua đề nghị\n"
      "  gắn vào phiếu (hết đếm 2 lần), > 0 = đang thiếu đúng khoản này (hết thiếu).")
unexplained.sort(key=lambda it: -abs(it[1]))
print(f"\n  {len(unexplained)} đơn lệch KHÔNG do dòng ghi nhầm / bỏ trống mã đơn — {UNEXPLAINED_TOP} đơn lệch lớn nhất:")
for order, gap in unexplained[:UNEXPLAINED_TOP]:
    print(f"      {order.name:<20} lệch {money(gap):>14}  {order.partner_id.commercial_partner_id.name}")
print(SEP)
