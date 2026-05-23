# -*- coding: utf-8 -*-
"""
patch_meta_picking_id.py
========================
Tìm picking PACK/OUT của một đơn hàng và gán picking_id đúng vào các meta.json
có picking_id=0 trong STREAM_DIR.

Chạy TRƯỚC retry_stuck_uploads.py:

    python odoo-bin shell -d <TEN_DATABASE> < bin/patch_meta_picking_id.py

Sau đó chạy:

    python odoo-bin shell -d <TEN_DATABASE> < bin/retry_stuck_uploads.py
"""

import os, json, glob, tempfile

STREAM_DIR = os.path.join(tempfile.gettempdir(), 'pack_streams')
SEP = "=" * 72

# ── Cấu hình: đơn hàng cần tìm picking ──────────────────────────────────────
# Đổi nếu cần tìm theo đơn hàng khác
ORDER_NAME = "DH125524949232025"
# Nếu đã biết picking_id cụ thể, điền vào đây để bỏ qua bước tìm kiếm (0 = tự tìm)
FORCE_PICKING_ID = 0
# ----------------------------------------------------------------------------

def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

section(f"1. TÌM PICKING CHO ĐƠN {ORDER_NAME}")

# Tìm tất cả picking PACK/OUT liên quan đến đơn hàng
if FORCE_PICKING_ID > 0:
    target_picking = env['stock.picking'].sudo().browse(FORCE_PICKING_ID)
    if not target_picking.exists():
        print(f"❌ ABORT: picking id={FORCE_PICKING_ID} không tồn tại")
        raise SystemExit(1)
    pack_pickings = target_picking
    print(f"  Sử dụng picking được chỉ định: {target_picking.name} (id={target_picking.id})")
else:
    sale = env['sale.order'].sudo().search([('name', '=', ORDER_NAME)], limit=1)
    if not sale:
        print(f"❌ ABORT: Không tìm thấy sale order '{ORDER_NAME}'")
        raise SystemExit(1)
    print(f"  ✅ Sale Order: {sale.name} (id={sale.id})")

    all_pickings = env['stock.picking'].sudo().search([
        ('sale_id', '=', sale.id),
        ('picking_type_id.sequence_code', 'in', ['PACK', 'OUT']),
    ])
    if not all_pickings:
        # Fallback: tìm theo origin
        all_pickings = env['stock.picking'].sudo().search([
            ('origin', 'ilike', ORDER_NAME),
            ('picking_type_id.sequence_code', 'in', ['PACK', 'OUT']),
        ])

    if not all_pickings:
        print(f"❌ ABORT: Không tìm thấy picking PACK/OUT cho đơn {ORDER_NAME}")
        raise SystemExit(1)

    print(f"\n  Tìm thấy {len(all_pickings)} picking PACK/OUT:")
    for p in all_pickings:
        print(f"    id={p.id}  {p.name}  state={p.state}  type={p.picking_type_id.sequence_code}")

    # Ưu tiên: picking có state=assigned/in_progress/done, type=PACK
    pack_pickings = all_pickings.filtered(
        lambda p: p.picking_type_id.sequence_code == 'PACK'
    )
    if not pack_pickings:
        pack_pickings = all_pickings

    target_picking = pack_pickings[0]
    print(f"\n  → Sẽ gán picking_id={target_picking.id} ({target_picking.name}) vào các meta file")

section("2. KIỂM TRA META FILES")

if not os.path.exists(STREAM_DIR):
    print(f"STREAM_DIR không tồn tại: {STREAM_DIR}")
    raise SystemExit(0)

meta_files = sorted(glob.glob(os.path.join(STREAM_DIR, '*.meta.json')))
print(f"Tìm thấy {len(meta_files)} meta.json\n")

zero_id_files = []
for mf in meta_files:
    try:
        with open(mf) as f:
            m = json.load(f)
        pid = int(m.get('picking_id') or 0)
        webm = m.get('path') or mf.replace('.meta.json', '.webm')
        has_webm = os.path.exists(webm)
        size_mb = os.path.getsize(webm) / 1024 / 1024 if has_webm else 0
        status = "✅" if has_webm and size_mb > 0.01 else "⚠️ "
        print(f"  {status} {os.path.basename(mf)}")
        print(f"      picking_id={pid}  webm={'✅ ' + f'{size_mb:.1f}MB' if has_webm else '❌ MISSING'}  last_index={m.get('last_index','?')}")
        if pid == 0 and has_webm and size_mb > 0.01:
            zero_id_files.append((mf, m))
    except Exception as ex:
        print(f"  ❌ Lỗi đọc {mf}: {ex}")

print(f"\n  → {len(zero_id_files)} file có picking_id=0 và webm hợp lệ sẽ được patch")

section("3. PATCH PICKING_ID")

patched = 0
for mf, m in zero_id_files:
    m['picking_id'] = target_picking.id
    with open(mf, 'w', encoding='utf-8') as f:
        json.dump(m, f)
    print(f"  ✅ Đã patch {os.path.basename(mf)} → picking_id={target_picking.id} ({target_picking.name})")
    patched += 1

print(f"\n  Đã patch {patched} file")
print(f"\n  BƯỚC TIẾP THEO:")
print(f"  1. Vào Odoo > Settings > Google Drive Integration > Re-authorize (nếu token còn expired)")
print(f"  2. Chạy: python odoo-bin shell -d <DB> < bin/retry_stuck_uploads.py")
print(f"\n{SEP}")
print("  PATCH HOÀN THÀNH")
print(SEP)
