#!/usr/bin/env python3
"""
debug_pick_02867.py - Kiểm tra KBC/PICK/02867 + SO S00200
Chạy: exec(open('debug_pick_02867.py').read())
"""
from datetime import datetime

PICKING_NAME = 'KBC/PICK/02867'
SO_NAME      = 'S00200'

def qr(ml):
    for f in ('quantity_product_uom', 'reserved_uom_qty'):
        v = getattr(ml, f, None)
        if v is not None: return float(v)
    return 0.0

def qd(ml):
    for f in ('quantity', 'qty_done'):
        v = getattr(ml, f, None)
        if v is not None: return float(v)
    return 0.0

def qi(pid, lid):
    q = env['stock.quant'].search([('product_id','=',pid),('location_id','=',lid)], limit=1)
    if not q: return (0,0,0)
    return float(q.quantity), float(q.reserved_quantity), float(q.available_quantity)

def ppc(child_loc, parent_loc_id):
    pp = getattr(child_loc, 'parent_path', None)
    if pp: return f'/{parent_loc_id}/' in pp
    loc = child_loc
    while loc:
        if loc.id == parent_loc_id: return True
        if loc.id == loc.location_id.id: break
        loc = loc.location_id
    return False

print("="*100)
print(f"DEBUG {PICKING_NAME} + SO {SO_NAME}  |  {datetime.now()}")
print("="*100)

# ── SO ──
so = env['sale.order'].search([('name','=',SO_NAME)], limit=1)
if so:
    print(f"\n>> SO: {so.name}  state={so.state}  id={so.id}")
    print(f"   Customer: {so.partner_id.display_name}")
    print(f"   Warehouse: {so.warehouse_id.name if so.warehouse_id else '-'}")
    all_picks = so.picking_ids.sorted('id')
    print(f"   Phieu lien quan ({len(all_picks)}):")
    for p in all_picks:
        print(f"     {p.name}  [{p.picking_type_id.sequence_code}]  state={p.state}  "
              f"backorder_of={p.backorder_id.name if p.backorder_id else '-'}  id={p.id}")
else:
    print(f"[!] Khong tim thay SO {SO_NAME}")

# ── PICKING chi tiết ──
pick = env['stock.picking'].search([('name','=',PICKING_NAME)], limit=1)
if not pick:
    print(f"\n[!] Khong tim thay picking {PICKING_NAME}")
    raise SystemExit

print(f"\n{'='*100}")
print(f"PICKING: {pick.name}  [{pick.picking_type_id.sequence_code}]  state={pick.state}  id={pick.id}")
print(f"{'='*100}")
print(f"  Header SRC : {pick.location_id.complete_name}  (id={pick.location_id.id})")
print(f"  Header DST : {pick.location_dest_id.complete_name}  (id={pick.location_dest_id.id})")
print(f"  Backorder of: {pick.backorder_id.name if pick.backorder_id else '-'}")
print(f"  Date done   : {pick.date_done}")
print(f"  Origin      : {pick.origin}")
if pick.sale_id:
    print(f"  SO          : {pick.sale_id.name}")

# ── MOVE LINES ──
print(f"\n  MOVE LINES ({len(pick.move_line_ids)}):")
for ml in pick.move_line_ids:
    pid = ml.product_id.id
    dc = ml.product_id.default_code or ''
    reserved = qr(ml)
    done = qd(ml)

    src_loc = ml.location_id
    dst_loc = ml.location_dest_id

    src_on, src_res, src_avail = qi(pid, src_loc.id)
    dst_on, dst_res, dst_avail = qi(pid, dst_loc.id)

    # Kiểm tra anomaly
    flags = []
    if src_loc.id == dst_loc.id:
        flags.append('*** SELF-TRANSFER (FROM==TO) -> net quant=0')
    if not ppc(src_loc, pick.location_id.id):
        flags.append(f'*** WRONG SRC: line.src={src_loc.complete_name} NOT child of picking.src={pick.location_id.complete_name}')
    if not ppc(dst_loc, pick.location_dest_id.id):
        flags.append(f'*** WRONG DST: line.dst={dst_loc.complete_name} NOT child of picking.dst={pick.location_dest_id.complete_name}')
    if pick.state == 'done' and dst_on == 0.0:
        flags.append('*** DONE nhung quant @ dich = 0')

    print(f"\n  [{dc}] {ml.product_id.display_name[:60]}")
    print(f"    lot={ml.lot_id.name if ml.lot_id else '-'}  reserved={reserved:.2f}  done={done:.2f}")
    print(f"    FROM: {src_loc.complete_name}  (id={src_loc.id})")
    print(f"      quant -> on_hand={src_on:.2f}  res={src_res:.2f}  avail={src_avail:.2f}")
    print(f"    TO  : {dst_loc.complete_name}  (id={dst_loc.id})")
    print(f"      quant -> on_hand={dst_on:.2f}  res={dst_res:.2f}  avail={dst_avail:.2f}")
    for f in flags:
        print(f"    {f}")

# ── STOCK.MOVE (parent) ──
print(f"\n  STOCK.MOVES ({len(pick.move_ids)}):")
for m in pick.move_ids:
    qty_val = float(getattr(m, 'quantity', getattr(m, 'quantity_done', 0.0)))
    dc = m.product_id.default_code or ''
    print(f"    [{dc}] {m.product_id.display_name[:50]}  state={m.state}  qty={qty_val:.2f}")
    print(f"      {m.location_id.complete_name} -> {m.location_dest_id.complete_name}")

# ── BACKORDER chain ──
print(f"\n{'='*100}")
print(f"BACKORDER CHAIN")
print(f"{'='*100}")
bo = pick
chain = [bo.name]
while bo.backorder_id:
    bo = bo.backorder_id
    chain.insert(0, bo.name)
# forward: tìm phiếu có backorder_id = pick
forward = env['stock.picking'].search([('backorder_id','=',pick.id)])
for fp in forward:
    chain.append(fp.name)
print(f"  Chain: {' -> '.join(chain)}")

for name in chain:
    cp = env['stock.picking'].search([('name','=',name)], limit=1)
    if not cp: continue
    print(f"\n  {cp.name}  [{cp.picking_type_id.sequence_code}]  state={cp.state}")
    print(f"    Header: {cp.location_id.complete_name} -> {cp.location_dest_id.complete_name}")
    for ml in cp.move_line_ids:
        dc = ml.product_id.default_code or ''
        done_v = qd(ml)
        res_v = qr(ml)
        src = ml.location_id.complete_name
        dst = ml.location_dest_id.complete_name
        flag = ''
        if not ppc(ml.location_id, cp.location_id.id):
            flag = '  *** WRONG SRC'
        if ml.location_id.id == ml.location_dest_id.id:
            flag = '  *** SELF-TRANSFER'
        print(f"    [{dc}] res={res_v:.2f} done={done_v:.2f}  {src} -> {dst}{flag}")

# ── DOWNSTREAM PACK/OUT ──
if so:
    print(f"\n{'='*100}")
    print(f"DOWNSTREAM PHIEU PACK/OUT cua SO {so.name}")
    print(f"{'='*100}")
    for p in so.picking_ids.sorted('id'):
        if p.picking_type_id.sequence_code in ('PACK', 'OUT'):
            print(f"\n  {p.name}  [{p.picking_type_id.sequence_code}]  state={p.state}")
            print(f"    Header: {p.location_id.complete_name} -> {p.location_dest_id.complete_name}")
            for ml in p.move_line_ids:
                dc = ml.product_id.default_code or ''
                pid = ml.product_id.id
                done_v = qd(ml)
                res_v = qr(ml)
                src_on, src_res, src_avail = qi(pid, ml.location_id.id)
                print(f"    [{dc}] res={res_v:.2f} done={done_v:.2f}")
                print(f"      FROM: {ml.location_id.complete_name}  (on_hand={src_on:.2f} avail={src_avail:.2f})")

# ── MESSAGE LOG ──
print(f"\n{'='*100}")
print(f"MESSAGE LOG {PICKING_NAME}")
print(f"{'='*100}")
import re
msgs = env['mail.message'].search([
    ('res_id','=',pick.id),('model','=','stock.picking'),
    ('message_type','in',['comment','notification','email']),
], order='date asc', limit=15)
for msg in msgs:
    body = re.sub(r'<[^>]+>','',(msg.body or '').replace('<br>',' ').replace('</p><p>',' | ')).strip()[:150]
    print(f"  [{msg.date}] {msg.author_id.name or '-'}: {body}")

print(f"\n{'='*100}")
print("DEBUG DONE")
print(f"{'='*100}")
