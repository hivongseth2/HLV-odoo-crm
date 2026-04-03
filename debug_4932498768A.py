#!/usr/bin/env python3
"""
Debug script: Tại sao 3 lệnh chuyển TSN/Stock → Khu vực đóng gói hoàn tất
nhưng chỉ có 2 con lên được?
Product: 4932498768A (Thước cuộn 5m 16" có nam châm MILWAUKEE)

Chạy: docker exec -it <container> odoo shell -d <db> < debug_4932498768A.py
Hoặc: python3 odoo-bin shell -d <db> < debug_4932498768A.py
"""
from datetime import datetime, timedelta

print("=" * 100)
print("DEBUG: Product 4932498768A - Chuyển TSN/Stock → Khu vực đóng gói")
print("=" * 100)

# 1. Tìm sản phẩm
product = env['product.product'].search([
    '|',
    ('default_code', '=', '4932498768A'),
    ('barcode', '=', '4932498768A'),
], limit=1)

if not product:
    product = env['product.product'].search([
        ('default_code', 'ilike', '4932498768A'),
    ], limit=1)

if not product:
    print("!!! KHÔNG TÌM THẤY SẢN PHẨM 4932498768A !!!")
    exit()

print(f"\n[1] SẢN PHẨM: {product.display_name} (id={product.id})")
print(f"    default_code={product.default_code}, barcode={product.barcode}")

# 2. Tìm tất cả location liên quan đến TSN
print("\n" + "=" * 100)
print("[2] CÁC LOCATION LIÊN QUAN ĐẾN TSN")
print("=" * 100)

tsn_locations = env['stock.location'].search([
    ('complete_name', 'ilike', 'TSN'),
    ('usage', '=', 'internal'),
])
for loc in tsn_locations:
    print(f"    id={loc.id} | {loc.complete_name} | usage={loc.usage}")

# Tìm TSN/Stock và TSN/Khu vực đóng gói
stock_loc = env['stock.location'].search([
    ('complete_name', 'ilike', 'TSN'),
    ('complete_name', 'ilike', 'Stock'),
    ('usage', '=', 'internal'),
])
pack_loc = env['stock.location'].search([
    ('complete_name', 'ilike', 'TSN'),
    '|',
    ('complete_name', 'ilike', 'đóng gói'),
    ('complete_name', 'ilike', 'dong goi'),
    ('usage', '=', 'internal'),
])
if not pack_loc:
    pack_loc = env['stock.location'].search([
        ('complete_name', 'ilike', 'TSN'),
        ('complete_name', 'ilike', 'Pack'),
        ('usage', '=', 'internal'),
    ])

print(f"\n    TSN/Stock locations: {[(l.id, l.complete_name) for l in stock_loc]}")
print(f"    TSN/Đóng gói locations: {[(l.id, l.complete_name) for l in pack_loc]}")

# 3. Tồn kho hiện tại tại tất cả TSN locations
print("\n" + "=" * 100)
print("[3] TỒN KHO HIỆN TẠI CỦA SẢN PHẨM TẠI TSN")
print("=" * 100)

all_quants = env['stock.quant'].search([
    ('product_id', '=', product.id),
    ('location_id', 'in', tsn_locations.ids),
])
for q in all_quants:
    print(f"    location={q.location_id.complete_name} (id={q.location_id.id}) | "
          f"on_hand={q.quantity} | reserved={q.reserved_quantity} | "
          f"available={q.available_quantity}")

total_on_hand = sum(q.quantity for q in all_quants)
total_reserved = sum(q.reserved_quantity for q in all_quants)
print(f"\n    >>> TỔNG on_hand={total_on_hand} | reserved={total_reserved} | available={total_on_hand - total_reserved}")

# 4. Tìm tất cả picking có product này, liên quan TSN, trong ngày 03/04/2026
print("\n" + "=" * 100)
print("[4] TẤT CẢ PICKING LIÊN QUAN ĐẾN SẢN PHẨM NÀY TRONG NGÀY 03/04")
print("=" * 100)

# Lấy ngày hôm nay (UTC) - cần điều chỉnh timezone
today_start = datetime(2026, 4, 2, 23, 0, 0)  # 6h sáng VN = 23h UTC ngày trước
today_end = datetime(2026, 4, 3, 23, 59, 59)

pickings_with_product = env['stock.picking'].search([
    ('move_ids.product_id', '=', product.id),
    ('date_done', '>=', today_start),
    ('date_done', '<=', today_end),
], order='date_done asc')

if not pickings_with_product:
    # Thử tìm rộng hơn
    pickings_with_product = env['stock.picking'].search([
        ('move_ids.product_id', '=', product.id),
        ('scheduled_date', '>=', today_start),
        ('scheduled_date', '<=', today_end),
    ], order='scheduled_date asc')

if not pickings_with_product:
    # Tìm tất cả picking gần đây
    pickings_with_product = env['stock.picking'].search([
        ('move_ids.product_id', '=', product.id),
        ('state', 'in', ['done', 'assigned', 'confirmed']),
    ], order='date_done desc', limit=20)

for p in pickings_with_product:
    moves = p.move_ids.filtered(lambda m: m.product_id.id == product.id)
    for m in moves:
        print(f"    picking={p.name} (id={p.id}) | state={p.state} | "
              f"date_done={p.date_done} | "
              f"from={m.location_id.complete_name} → to={m.location_dest_id.complete_name} | "
              f"demand={m.product_uom_qty} | done={m.quantity} | "
              f"move_state={m.state}")
        for ml in m.move_line_ids:
            print(f"        move_line id={ml.id} | state={ml.state} | "
                  f"from={ml.location_id.complete_name} → to={ml.location_dest_id.complete_name} | "
                  f"qty={ml.quantity}")

# 5. Tìm cụ thể các picking TSN/Stock → Khu vực đóng gói
print("\n" + "=" * 100)
print("[5] CÁC PICKING TSN/Stock → Khu vực đóng gói (PICK operations)")
print("=" * 100)

all_loc_ids = stock_loc.ids + pack_loc.ids
pick_moves = env['stock.move'].search([
    ('product_id', '=', product.id),
    ('state', '=', 'done'),
    ('date', '>=', today_start),
    ('date', '<=', today_end),
], order='date asc')

if not pick_moves:
    pick_moves = env['stock.move'].search([
        ('product_id', '=', product.id),
        ('state', '=', 'done'),
    ], order='date desc', limit=20)

for m in pick_moves:
    is_stock_to_pack = any(
        'Stock' in (m.location_id.complete_name or '') and
        ('đóng gói' in (m.location_dest_id.complete_name or '').lower() or
         'pack' in (m.location_dest_id.complete_name or '').lower())
        for _ in [1]
    )
    marker = " <<<< STOCK→PACK" if is_stock_to_pack else ""
    print(f"    move_id={m.id} | picking={m.picking_id.name} (id={m.picking_id.id}) | "
          f"date={m.date} | "
          f"from={m.location_id.complete_name} → to={m.location_dest_id.complete_name} | "
          f"demand={m.product_uom_qty} | done={m.quantity} | state={m.state}{marker}")
    for ml in m.move_line_ids:
        print(f"        move_line id={ml.id} | state={ml.state} | "
              f"from={ml.location_id.complete_name} → to={ml.location_dest_id.complete_name} | "
              f"qty={ml.quantity}")

# 6. Tìm picking theo tên từ ảnh (S01431, S01432, S01434)
print("\n" + "=" * 100)
print("[6] TÌM CỤ THỂ CÁC PICKING TỪ ẢNH: S01431, S01432, S01434")
print("=" * 100)

for so_name in ['S01431', 'S01432', 'S01434']:
    # Tìm theo sale order origin
    pickings = env['stock.picking'].search([
        '|', '|',
        ('origin', 'ilike', so_name),
        ('name', 'ilike', so_name),
        ('group_id.name', 'ilike', so_name),
    ])
    if not pickings:
        print(f"\n    [{so_name}] Không tìm thấy picking nào")
        continue

    for p in pickings:
        moves = p.move_ids.filtered(lambda m: m.product_id.id == product.id)
        if not moves:
            continue
        print(f"\n    [{so_name}] picking={p.name} (id={p.id}) | state={p.state} | "
              f"picking_type={p.picking_type_id.name} | "
              f"date_done={p.date_done} | origin={p.origin}")
        print(f"    [{so_name}] from={p.location_id.complete_name} → to={p.location_dest_id.complete_name}")

        for m in moves:
            print(f"    [{so_name}] MOVE id={m.id} | state={m.state} | "
                  f"demand={m.product_uom_qty} | done={m.quantity} | "
                  f"from={m.location_id.complete_name} → to={m.location_dest_id.complete_name}")
            for ml in m.move_line_ids:
                print(f"    [{so_name}]   LINE id={ml.id} | state={ml.state} | "
                      f"qty={ml.quantity} | "
                      f"from={ml.location_id.complete_name} → to={ml.location_dest_id.complete_name}")

        # Kiểm tra message log (xem có bị auto-adjust không)
        messages = env['mail.message'].search([
            ('res_id', '=', p.id),
            ('model', '=', 'stock.picking'),
            ('body', 'ilike', 'điều chỉnh'),
        ], limit=5)
        for msg in messages:
            print(f"    [{so_name}] !!! MESSAGE: {msg.date} | {msg.body[:200]}")

        # Tìm backorder
        backorders = env['stock.picking'].search([
            ('backorder_id', '=', p.id),
        ])
        for bo in backorders:
            print(f"    [{so_name}] BACKORDER: {bo.name} (id={bo.id}) | state={bo.state}")
            bo_moves = bo.move_ids.filtered(lambda m: m.product_id.id == product.id)
            for bm in bo_moves:
                print(f"    [{so_name}]   BO MOVE: demand={bm.product_uom_qty} | done={bm.quantity} | state={bm.state}")

# 7. Kiểm tra stock.move.line đã done liên quan đóng gói
print("\n" + "=" * 100)
print("[7] TẤT CẢ MOVE LINES ĐÃ DONE CỦA SẢN PHẨM TRONG NGÀY")
print("=" * 100)

done_lines = env['stock.move.line'].search([
    ('product_id', '=', product.id),
    ('state', '=', 'done'),
    ('date', '>=', today_start),
    ('date', '<=', today_end),
], order='date asc')

if not done_lines:
    done_lines = env['stock.move.line'].search([
        ('product_id', '=', product.id),
        ('state', '=', 'done'),
    ], order='date desc', limit=30)

for dl in done_lines:
    print(f"    line_id={dl.id} | picking={dl.picking_id.name} | date={dl.date} | "
          f"from={dl.location_id.complete_name} → to={dl.location_dest_id.complete_name} | "
          f"qty={dl.quantity} | state={dl.state}")

# 8. Kiểm tra picking đang pending (chưa done) có liên quan product này không
print("\n" + "=" * 100)
print("[8] PICKING ĐANG PENDING (chưa done) CÓ SẢN PHẨM NÀY")
print("=" * 100)

pending_moves = env['stock.move'].search([
    ('product_id', '=', product.id),
    ('state', 'not in', ['done', 'cancel']),
])
for m in pending_moves:
    print(f"    move_id={m.id} | picking={m.picking_id.name} (id={m.picking_id.id}) | "
          f"state={m.state} | picking_state={m.picking_id.state} | "
          f"demand={m.product_uom_qty} | reserved={m.quantity} | "
          f"from={m.location_id.complete_name} → to={m.location_dest_id.complete_name}")
    for ml in m.move_line_ids:
        print(f"        line_id={ml.id} | qty={ml.quantity} | state={ml.state}")

# 9. Kiểm tra xem button_validate có sửa qty không (tìm trong message)
print("\n" + "=" * 100)
print("[9] KIỂM TRA CÁC PICKING CÓ BỊ AUTO-ADJUST QTY KHÔNG")
print("=" * 100)

adjusted_messages = env['mail.message'].search([
    ('model', '=', 'stock.picking'),
    ('body', 'ilike', 'điều chỉnh'),
    ('date', '>=', today_start),
    ('date', '<=', today_end),
], limit=20, order='date desc')

if not adjusted_messages:
    adjusted_messages = env['mail.message'].search([
        ('model', '=', 'stock.picking'),
        ('body', 'ilike', 'điều chỉnh'),
    ], limit=10, order='date desc')

for msg in adjusted_messages:
    picking = env['stock.picking'].browse(msg.res_id)
    has_product = any(m.product_id.id == product.id for m in picking.move_ids)
    if has_product:
        print(f"    !!! PICKING={picking.name} | date={msg.date}")
        print(f"    !!! MESSAGE: {msg.body[:500]}")
        print()

# 10. Kiểm tra stock.quant history (nếu có tracking module)
print("\n" + "=" * 100)
print("[10] TỔNG KẾT")
print("=" * 100)

# Đếm tổng từ done move lines
total_to_pack = 0
total_from_pack = 0

for dl in done_lines:
    loc_from = dl.location_id.complete_name or ''
    loc_to = dl.location_dest_id.complete_name or ''

    is_to_pack = ('đóng gói' in loc_to.lower() or 'pack' in loc_to.lower()) and 'TSN' in loc_to
    is_from_pack = ('đóng gói' in loc_from.lower() or 'pack' in loc_from.lower()) and 'TSN' in loc_from

    if is_to_pack and not is_from_pack:
        total_to_pack += dl.quantity
    elif is_from_pack and not is_to_pack:
        total_from_pack += dl.quantity

print(f"    Tổng SL chuyển VÀO khu vực đóng gói TSN (done): {total_to_pack}")
print(f"    Tổng SL chuyển RA khỏi khu vực đóng gói TSN (done): {total_from_pack}")
print(f"    Net tại đóng gói: {total_to_pack - total_from_pack}")

print("\n" + "=" * 100)
print("DEBUG XONG. Kiểm tra log ở trên để tìm nguyên nhân.")
print("=" * 100)
