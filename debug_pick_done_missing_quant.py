#!/usr/bin/env python3
"""
debug_pick_done_missing_quant.py

Kiểm tra SO S01672 - sản phẩm [M18 FID3-0X]:
  Phiếu PICK (GYKXUPLA) đã DONE - chuyển 1 con lên khu vực đóng gói
  Nhưng tại vị trí đích quant = 0

Mục tiêu truy vết:
  1. Hàng từ PICK thực sự đổ về đâu?      (stock.move.line.location_dest_id)
  2. Tại đích (packing zone) hiện có gì?  (stock.quant)
  3. Phiếu PACK downstream đang ở đâu?    (state, move_lines)
  4. Có quant nào bị "nhảy" sang sublocation lạ không?
  5. Lịch sử stock.move của sản phẩm trong kho TSN gần nhất

Chạy: exec(open('debug_pick_done_missing_quant.py').read())
"""

import re
from datetime import datetime, timedelta

SO_NAME      = 'S01672'
PRODUCT_CODE = 'M18 FID3-0X'          # default_code hoặc một phần tên

def strip_html(html):
    return re.sub(r'<[^>]+>', '', (html or '').replace('<br>', ' ').replace('</p><p>', ' | ')).strip()[:150]

def qty_reserved(ml):
    for f in ('quantity_product_uom', 'reserved_uom_qty'):
        v = getattr(ml, f, None)
        if v is not None:
            return float(v)
    return 0.0

def qty_done(ml):
    for f in ('quantity', 'qty_done'):
        v = getattr(ml, f, None)
        if v is not None:
            return float(v)
    return 0.0

def quant_info(product_id, location_id):
    q = env['stock.quant'].search([
        ('product_id', '=', product_id),
        ('location_id', '=', location_id),
    ], limit=1)
    if not q:
        return (0.0, 0.0, 0.0)
    return float(q.quantity), float(q.reserved_quantity), float(q.available_quantity)

def is_child_location(child_loc, parent_loc):
    """Kiểm tra child_loc có nằm trong parent_loc không (dùng parent_path)."""
    pp = getattr(child_loc, 'parent_path', None)
    if pp:
        return f'/{parent_loc.id}/' in pp
    # fallback: dùng complete_name
    return child_loc.complete_name.startswith(parent_loc.complete_name)

print("=" * 100)
print(f"DEBUG PICK-DONE MISSING QUANT  |  SO: {SO_NAME}  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 100)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Tìm SO
# ─────────────────────────────────────────────────────────────────────────────
so = env['sale.order'].search([('name', '=', SO_NAME)], limit=1)
if not so:
    print(f"[!] Khong tim thay SO: {SO_NAME}")
    raise SystemExit

print(f"\n>> SO: {so.name}  state={so.state}  id={so.id}")
print(f"   Customer : {so.partner_id.display_name}")
print(f"   Warehouse: {so.warehouse_id.name if so.warehouse_id else '-'}")

wh = so.warehouse_id

# ─────────────────────────────────────────────────────────────────────────────
# 2. Tất cả pickings của SO
# ─────────────────────────────────────────────────────────────────────────────
pickings = so.picking_ids.sorted('id')
print(f"\n>> Tong so phieu: {len(pickings)}")
for p in pickings:
    print(f"   {p.name}  type={p.picking_type_id.sequence_code}  state={p.state}  id={p.id}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. CHI TIẾT TẤT CẢ MOVE LINES trong mỗi picking (không lọc theo product)
#    Vì đây là combo/kit -> picking có các component, không phải bán thành phẩm
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*100}")
print(f"CHI TIET TAT CA MOVE LINES TRONG PHIEU (combo = components)")
print(f"{'='*100}")

for p in pickings:
    print(f"\n-- {p.name}  [{p.picking_type_id.sequence_code}]  state={p.state}  id={p.id}")
    print(f"   Header: {p.location_id.complete_name}  ->  {p.location_dest_id.complete_name}")

    if not p.move_line_ids:
        print(f"   (khong co move_line)")
        continue

    for ml in p.move_line_ids:
        qr = qty_reserved(ml)
        qd = qty_done(ml)
        pid = ml.product_id.id
        dc = ml.product_id.default_code or ''
        name = ml.product_id.display_name[:60]

        src_on, src_res, src_avail = quant_info(pid, ml.location_id.id)
        dst_on, dst_res, dst_avail = quant_info(pid, ml.location_dest_id.id)

        flag = ''
        if p.state == 'done' and dst_on == 0.0:
            flag = '  *** [!] DONE nhung quant @ dich = 0'
        elif p.state == 'assigned' and src_on < qr - 0.001:
            flag = f'  *** [!] OVER-RESERVED: on_hand ({src_on:.2f}) < reserved ({qr:.2f})'

        print(f"   [{dc}] {name}")
        print(f"     lot={ml.lot_id.name if ml.lot_id else '-'}  "
              f"qty_reserved={qr:.2f}  qty_done={qd:.2f}{flag}")
        print(f"     FROM: {ml.location_id.complete_name}  "
              f"(on_hand={src_on:.2f} res={src_res:.2f} avail={src_avail:.2f})")
        print(f"     TO  : {ml.location_dest_id.complete_name}  "
              f"(on_hand={dst_on:.2f} res={dst_res:.2f} avail={dst_avail:.2f})")

    # Message log
    msgs = env['mail.message'].search([
        ('res_id', '=', p.id),
        ('model', '=', 'stock.picking'),
        ('message_type', 'in', ['comment', 'notification', 'email']),
    ], order='date desc', limit=5)
    if msgs:
        print(f"   HISTORY:")
        for msg in reversed(msgs):
            print(f"     [{msg.date}] {strip_html(msg.body)[:120]}")

# ─────────────────────────────────────────────────────────────────────────────
# 4. Tìm component liên quan đến PRODUCT_CODE trong các pickings
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*100}")
print(f"COMPONENT CO CODE '{PRODUCT_CODE}' TRONG PHIEU")
print(f"{'='*100}")

found_components = set()
for p in pickings:
    for ml in p.move_line_ids:
        dc = (ml.product_id.default_code or '').upper()
        nm = ml.product_id.display_name.upper()
        kw = PRODUCT_CODE.upper().replace(' ', '')
        if kw in dc.replace(' ', '') or kw in nm.replace(' ', ''):
            found_components.add(ml.product_id.id)
            pid = ml.product_id.id
            qr = qty_reserved(ml)
            qd = qty_done(ml)
            dst_on, dst_res, dst_avail = quant_info(pid, ml.location_dest_id.id)
            src_on, src_res, src_avail = quant_info(pid, ml.location_id.id)
            print(f"\n  {p.name} [{p.picking_type_id.sequence_code}] state={p.state}")
            print(f"  [{ml.product_id.default_code}] {ml.product_id.display_name[:70]}")
            print(f"    qty_reserved={qr:.2f}  qty_done={qd:.2f}")
            print(f"    FROM: {ml.location_id.complete_name}  (on_hand={src_on:.2f})")
            print(f"    TO  : {ml.location_dest_id.complete_name}  (on_hand={dst_on:.2f} res={dst_res:.2f} avail={dst_avail:.2f})")
            if p.state == 'done' and dst_on == 0.0:
                print(f"    *** [!] PICK DONE nhung quant @ dich = 0!")

if not found_components:
    print(f"  Khong tim thay component nao co code '{PRODUCT_CODE}' trong phieu.")
    print(f"  => Day la combo/kit - xem toan bo move lines o section 3.")

# ─────────────────────────────────────────────────────────────────────────────
# 5. Truy tìm TOÀN BỘ quant tại packing zone (tất cả sản phẩm = 0)
#    Kiểm tra packing zone có hàng không
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*100}")
print(f"QUANT TAI PACKING ZONE (tat ca san pham, co so luong > 0)")
print(f"{'='*100}")

# Lấy dest location từ PACK picking làm packing zone
pack_zone_ids = set()
for p in pickings:
    if p.picking_type_id.sequence_code == 'PACK':
        pack_zone_ids.add(p.location_id.id)
    if p.picking_type_id.sequence_code == 'PICK':
        pack_zone_ids.add(p.location_dest_id.id)

for loc_id in pack_zone_ids:
    loc = env['stock.location'].browse(loc_id)
    print(f"\n  Zone: {loc.complete_name}  (id={loc_id})")
    # Tất cả quant trong zone này (child_of)
    zone_quants = env['stock.quant'].search([
        ('location_id', 'child_of', loc_id),
        ('quantity', '!=', 0),
    ], order='product_id, location_id')
    if not zone_quants:
        print(f"  [!] PACKING ZONE TRONG RONG - khong co quant nao co so luong.")
    else:
        for q in zone_quants:
            dc = q.product_id.default_code or ''
            print(f"    [{dc}] {q.product_id.display_name[:50]}")
            print(f"      @ {q.location_id.complete_name}")
            print(f"      on_hand={q.quantity:.2f}  reserved={q.reserved_quantity:.2f}  "
                  f"available={q.available_quantity:.2f}")

# ─────────────────────────────────────────────────────────────────────────────
# 6. Lịch sử stock.move của tất cả component (7 ngày gần nhất, state=done)
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*100}")
print(f"LICH SU STOCK.MOVE cho cac component trong phieu (done, 7 ngay)")
print(f"{'='*100}")

# Lấy tất cả product_id từ pickings
all_product_ids = list({ml.product_id.id for p in pickings for ml in p.move_line_ids})

since = datetime.now() - timedelta(days=7)

# Query riêng từng product để tránh limit bị 1 product chiếm hết
for pid in all_product_ids:
    prod = env['product.product'].browse(pid)
    moves = env['stock.move'].search([
        ('product_id', '=', pid),
        ('state', '=', 'done'),
        ('date', '>=', since),
    ], order='date desc', limit=20)
    if not moves:
        continue
    dc_hdr = prod.default_code or str(pid)
    print(f"\n  --- [{dc_hdr}] {prod.display_name[:60]} ({len(moves)} moves) ---")
    for m in moves:
        qty_val = float(getattr(m, 'quantity', getattr(m, 'quantity_done', 0.0)))
        pick_name = m.picking_id.name if m.picking_id else '(no picking)'
        so_ref = ''
        if m.picking_id and m.picking_id.sale_id:
            so_ref = f"  SO={m.picking_id.sale_id.name}"
        print(f"  [{m.date}] {pick_name}  qty={qty_val:.2f}{so_ref}")
        print(f"    {m.location_id.complete_name}  ->  {m.location_dest_id.complete_name}")

print(f"\n{'='*100}")
print("DEBUG DONE")
print(f"{'='*100}")
