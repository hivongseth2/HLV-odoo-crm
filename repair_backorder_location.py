#!/usr/bin/env python3
"""
repair_backorder_location.py
Sửa phiếu backorder bị lỗi vị trí do JS barcode đè sai.

Lỗi đã xác nhận:
  KBC/PICK/02858 (backorder của 02842):
  - move.line.location_id = KBC/Tồn kho/A1-T1/Thung-2  (đã hết hàng)
  - qty_done = 1.00 trên phiếu assigned  (JS pre-fill từ session cũ)
  - Header location_id = KBC/Tồn kho  (đúng)
  => Unreserve + re-assign để Odoo tìm đúng vị trí có hàng

Chạy: exec(open('repair_backorder_location.py').read())
"""

import re
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
PICKING_NAME   = 'KBC/PICK/02858'
DRY_RUN        = True   # True = chỉ in, không sửa. Đặt False để thực sự sửa.
# ─────────────────────────────────────────────────────────────────────────────

def strip_html(html):
    return re.sub(r'<[^>]+>', '', (html or '').replace('<br>', ' ')).strip()[:120]

print("=" * 90)
print(f"REPAIR BACKORDER LOCATION  |  {PICKING_NAME}  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"DRY_RUN = {DRY_RUN}   (set DRY_RUN=False de thuc su sua)")
print("=" * 90)

# ── 1. Tìm phiếu ─────────────────────────────────────────────────────────────
picking = env['stock.picking'].search([('name', '=', PICKING_NAME)], limit=1)
if not picking:
    print(f"[!] Khong tim thay phieu: {PICKING_NAME}")
    raise SystemExit

print(f"\n>> {picking.name}  state={picking.state}  id={picking.id}")
print(f"   Header From: {picking.location_id.complete_name}")

if picking.state == 'done':
    print("[!] Phieu da DONE, khong can sua.")
    raise SystemExit

if picking.state == 'cancel':
    print("[!] Phieu da CANCEL.")
    raise SystemExit

# ── 2. Chẩn đoán trước khi sửa ───────────────────────────────────────────────
print(f"\n--- TRANG THAI TRUOC KHI SUA ---")
for ml in picking.move_line_ids:
    qty_res = getattr(ml, 'quantity_product_uom', getattr(ml, 'reserved_uom_qty', 0.0))
    qty_dn  = getattr(ml, 'quantity', getattr(ml, 'qty_done', 0.0))
    quant = env['stock.quant'].search([
        ('product_id', '=', ml.product_id.id),
        ('location_id', '=', ml.location_id.id),
    ], limit=1)
    on_hand = float(quant.quantity) if quant else 0.0
    print(f"  [{ml.product_id.default_code}] {ml.product_id.display_name[:45]}")
    print(f"    location : {ml.location_id.complete_name}")
    print(f"    qty_res  : {float(qty_res):.2f}  qty_done : {float(qty_dn):.2f}")
    print(f"    on_hand @ location : {on_hand:.2f}")

# ── 3. Tìm vị trí thực tế có hàng ────────────────────────────────────────────
print(f"\n--- TIM VI TRI CO HANG THUC TE ---")
parent_location = picking.location_id   # KBC/Tồn kho

for move in picking.move_ids:
    if move.state in ('done', 'cancel'):
        continue
    product = move.product_id
    demand  = move.product_uom_qty
    print(f"\n  [{product.default_code}] {product.display_name[:50]}  demand={demand:.2f}")

    # Tìm quants trong parent location
    quants = env['stock.quant'].search([
        ('product_id', '=', product.id),
        ('location_id', 'child_of', parent_location.id),
        ('quantity', '>', 0),
    ], order='location_id, quantity desc')

    if not quants:
        print("    [!] KHONG CO TON KHO TRONG KHO - kiem tra lai!")
    else:
        for q in quants:
            print(f"    OK: {q.location_id.complete_name}  "
                  f"on_hand={q.quantity:.2f}  reserved={q.reserved_quantity:.2f}  "
                  f"available={q.available_quantity:.2f}")

# ── 4. Thực hiện sửa ─────────────────────────────────────────────────────────
print(f"\n--- HANH DONG SUA CHUA ---")

if DRY_RUN:
    print("[DRY RUN] Se thuc hien cac buoc sau:")
    print("  1. Reset qty_done ve 0 tren tat ca move.lines")
    print("  2. do_unreserve()  -> giai phong reserve sai")
    print("  3. action_assign() -> Odoo tu tim vi tri dung co hang")
    print("\n  => Dat DRY_RUN = False de thuc su chay")
else:
    print("[LIVE] Bat dau sua...")

    # Bước 1: Reset qty_done về 0
    print("  [1] Reset qty_done ve 0...")
    for ml in picking.move_line_ids:
        try:
            if hasattr(ml, 'quantity'):        # Odoo 18
                ml.write({'quantity': 0.0})
            elif hasattr(ml, 'qty_done'):      # Odoo 16/17
                ml.write({'qty_done': 0.0})
        except Exception as e:
            print(f"      WARN: {e}")
    env.cr.commit()
    print("     Done.")

    # Bước 2: Unreserve (giải phóng reservation sai)
    print("  [2] do_unreserve()...")
    try:
        picking.do_unreserve()
        env.cr.commit()
        print("     Done.")
    except Exception as e:
        print(f"      ERROR: {e}")
        raise

    # Bước 3: Re-assign
    print("  [3] action_assign()...")
    try:
        picking.action_assign()
        env.cr.commit()
        print("     Done.")
    except Exception as e:
        print(f"      ERROR: {e}")
        raise

    # ── 5. Chẩn đoán sau khi sửa ─────────────────────────────────────────────
    print(f"\n--- TRANG THAI SAU KHI SUA ---")
    picking.invalidate_recordset()
    print(f"  state = {picking.state}")
    for ml in picking.move_line_ids:
        qty_res = getattr(ml, 'quantity_product_uom', getattr(ml, 'reserved_uom_qty', 0.0))
        qty_dn  = getattr(ml, 'quantity', getattr(ml, 'qty_done', 0.0))
        quant = env['stock.quant'].search([
            ('product_id', '=', ml.product_id.id),
            ('location_id', '=', ml.location_id.id),
        ], limit=1)
        on_hand  = float(quant.quantity)          if quant else 0.0
        avail    = float(quant.available_quantity) if quant else 0.0
        ok = "[OK]" if on_hand >= float(qty_res) else "[!!]"
        print(f"  {ok} [{ml.product_id.default_code}] {ml.product_id.display_name[:45]}")
        print(f"       NEW location : {ml.location_id.complete_name}")
        print(f"       qty_res={float(qty_res):.2f}  qty_done={float(qty_dn):.2f}")
        print(f"       on_hand={on_hand:.2f}  available={avail:.2f}")

    print(f"\n[DONE] Sua xong {PICKING_NAME}")

print(f"\n{'='*90}")
print("REPAIR SCRIPT DONE")
print(f"{'='*90}")
