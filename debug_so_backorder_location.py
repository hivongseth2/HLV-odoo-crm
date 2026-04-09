#!/usr/bin/env python3
"""
debug_so_backorder_location.py
Kiểm tra SO và chuỗi phiếu liên quan (Odoo 18):
  - Trạng thái phiếu PICK/PACK/OUT
  - Chuỗi backorder
  - Vị trí của move.line so với quant thực tế
  - Phát hiện vị trí bị đè sai bởi JS barcode

Odoo 18 field names:
  stock.move.line:  quantity           (qty done)
                    quantity_product_uom (qty reserved, in product UoM)
  stock.move:       quantity           (qty done aggregate)
                    product_uom_qty    (demand)

Chạy trong Odoo shell (không cần docker):
  Mở terminal server → odoo shell -d <dbname>
  Sau đó: exec(open('debug_so_backorder_location.py').read())
"""

import re
import sys
from datetime import datetime

SO_NAME = 'S00183'

# Helper: lấy field an toàn (tương thích cả Odoo 16/17/18)
def _qty_reserved(ml):
    """Số lượng đã reserve trên move.line (Odoo 18 = quantity_product_uom)"""
    for f in ('quantity_product_uom', 'reserved_uom_qty', 'product_uom_qty'):
        v = getattr(ml, f, None)
        if v is not None:
            return float(v)
    return 0.0

def _qty_done(ml):
    """Số lượng đã done trên move.line (Odoo 18 = quantity)"""
    for f in ('quantity', 'qty_done'):
        v = getattr(ml, f, None)
        if v is not None:
            return float(v)
    return 0.0

def strip_html(html):
    return re.sub(r'<[^>]+>', '', (html or '').replace('<br>', ' ').replace('</p><p>', ' | ')).strip()

print("=" * 100)
print(f"DEBUG BACKORDER LOCATION  |  SO: {SO_NAME}  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 100)

# ──────────────────────────────────────────────────────────────────────────────
# 1. Tìm Sale Order
# ──────────────────────────────────────────────────────────────────────────────
so = env['sale.order'].search([('name', '=', SO_NAME)], limit=1)
if not so:
    print(f"KHONG TIM THAY SO: {SO_NAME}")
    sys.exit()

print(f"\n>> SO: {so.name}  |  state={so.state}  |  id={so.id}")
print(f"  Customer : {so.partner_id.display_name}")
print(f"  Warehouse: {so.warehouse_id.name if so.warehouse_id else '-'}")

# ──────────────────────────────────────────────────────────────────────────────
# 2. Lấy tất cả pickings
# ──────────────────────────────────────────────────────────────────────────────
pickings = so.picking_ids.sorted('id')
print(f"\n>> Tong so phieu lien quan: {len(pickings)}")

for p in pickings:
    print(f"\n{'─'*100}")
    bo_label = f"  [BACKORDER cua: {p.backorder_id.name}]" if p.backorder_id else ""
    print(f">> {p.name}  |  state={p.state}  |  id={p.id}{bo_label}")
    print(f"   Type: {p.picking_type_id.sequence_code}  |  "
          f"From: {p.location_id.complete_name}  ->  To: {p.location_dest_id.complete_name}")
    print(f"   Scheduled: {p.scheduled_date}  |  Done: {p.date_done}")

    # ── Move lines ────────────────────────────────────────────────────────────
    print(f"\n   MOVE LINES {'─'*85}")
    for ml in p.move_line_ids:
        product_code = ml.product_id.default_code or '?'
        loc_from     = ml.location_id.complete_name
        loc_to       = ml.location_dest_id.complete_name
        qty_res      = _qty_reserved(ml)
        qty_dn       = _qty_done(ml)
        lot_name     = ml.lot_id.name if ml.lot_id else '-'

        # Tồn kho thực tế tại vị trí được gán
        quant = env['stock.quant'].search([
            ('product_id', '=', ml.product_id.id),
            ('location_id', '=', ml.location_id.id),
        ], limit=1)
        on_hand   = float(quant.quantity)           if quant else 0.0
        reserved  = float(quant.reserved_quantity)  if quant else 0.0
        available = float(quant.available_quantity) if quant else 0.0

        # Cờ cảnh báo (chỉ với phiếu chưa done)
        warn = ''
        if p.state not in ('done', 'cancel'):
            if not quant:
                warn = '[!] KHONG CO QUANT TAI VI TRI NAY!'
            elif on_hand <= 0:
                warn = '[!] TON KHO = 0 TAI VI TRI NAY!'
            elif available < qty_res:
                warn = f'[~] Ton kha dung ({available:.1f}) < yeu cau ({qty_res:.1f})'

        print(f"    [{product_code}] {ml.product_id.display_name[:55]}")
        print(f"      qty_reserved={qty_res:.2f}  qty_done={qty_dn:.2f}  lot={lot_name}")
        print(f"      FROM: {loc_from}")
        print(f"      TO  : {loc_to}")
        print(f"      QUANT @ FROM -> on_hand={on_hand:.2f}  reserved={reserved:.2f}  available={available:.2f}")
        if warn:
            print(f"      *** {warn}")

    # ── Moves chưa có lines ───────────────────────────────────────────────────
    moves_no_lines = p.move_ids.filtered(lambda m: not m.move_line_ids and m.state not in ('done', 'cancel'))
    if moves_no_lines:
        print(f"\n   MOVES KHONG CO LINES (chua reserve) {'─'*60}")
        for m in moves_no_lines:
            print(f"    [{m.product_id.default_code}] {m.product_id.display_name[:55]}")
            print(f"      demand={m.product_uom_qty:.2f}  state={m.state}")
            print(f"      Expected FROM: {m.location_id.complete_name}")

    # ── Message log ───────────────────────────────────────────────────────────
    messages = env['mail.message'].search([
        ('res_id', '=', p.id),
        ('model', '=', 'stock.picking'),
        ('message_type', 'in', ['comment', 'notification', 'email']),
    ], order='date desc', limit=6)
    if messages:
        print(f"\n   HISTORY (6 gan nhat) {'─'*75}")
        for msg in reversed(messages):
            print(f"    [{msg.date}] {strip_html(msg.body)[:130]}")

# ──────────────────────────────────────────────────────────────────────────────
# 3. Chuỗi backorder (tree)
# ──────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*100}")
print("CHUOI BACKORDER TREE")
print(f"{'='*100}")

def build_tree(all_p, parent_id=False, indent=0):
    if parent_id:
        children = [p for p in all_p if p.backorder_id.id == parent_id]
    else:
        children = [p for p in all_p if not p.backorder_id]
    for p in sorted(children, key=lambda x: x.id):
        prefix = "  " * indent + ("L-- " if indent else ">> ")
        print(f"{prefix}{p.name}  state={p.state}  ({len(p.move_line_ids)} lines)")
        build_tree(all_p, p.id, indent + 1)

build_tree(list(pickings))

# ──────────────────────────────────────────────────────────────────────────────
# 4. Tổng hợp cảnh báo
# ──────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*100}")
print("TONG HOP CANH BAO")
print(f"{'='*100}")

problems = []
for p in pickings:
    if p.state in ('done', 'cancel'):
        continue
    for ml in p.move_line_ids:
        quant = env['stock.quant'].search([
            ('product_id', '=', ml.product_id.id),
            ('location_id', '=', ml.location_id.id),
        ], limit=1)
        on_hand = float(quant.quantity) if quant else 0.0
        if not quant or on_hand <= 0:
            problems.append(
                f"[{p.name}] [{ml.product_id.default_code}] {ml.product_id.display_name[:40]} "
                f"-> vi tri '{ml.location_id.complete_name}'  ton_kho={on_hand}"
            )

if problems:
    print(f"\n[!] Phat hien {len(problems)} vi tri bi gan sai / khong co hang:")
    for prob in problems:
        print(f"  * {prob}")
else:
    print("\n[OK] Khong phat hien loi vi tri.")

# ──────────────────────────────────────────────────────────────────────────────
# 5. Kiểm tra xem phiếu backorder có location bất thường không
#    (location của move.line != location_id của picking header)
# ──────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*100}")
print("KIEM TRA LOCATION BI DE SAI (Frontend override)")
print(f"{'='*100}")

override_problems = []
for p in pickings:
    if p.state in ('done', 'cancel'):
        continue
    expected_loc_id = p.location_id.id
    for ml in p.move_line_ids:
        if ml.location_id.id != expected_loc_id:
            override_problems.append(
                f"[{p.name}] [{ml.product_id.default_code}] {ml.product_id.display_name[:40]}\n"
                f"    Header location : {p.location_id.complete_name}\n"
                f"    MoveLine location: {ml.location_id.complete_name}  <-- BI DE SAI?"
            )

if override_problems:
    print(f"\n[!] Phat hien {len(override_problems)} dong co location khac header (nghi bi JS de):")
    for op in override_problems:
        print(f"\n  {op}")
else:
    print("\n[OK] Tat ca move.line dung location voi header picking.")

print(f"\n{'='*100}")
print("DEBUG DONE")
print(f"{'='*100}")
