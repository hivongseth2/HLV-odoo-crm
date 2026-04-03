#!/usr/bin/env python3
"""
Debug v2: Xác nhận TSN/Stock = 550 thay vì 549
Kiểm tra PACK/08012 (S01434) đã unreserve trả hàng về Stock chưa

Chạy: docker exec -it <container> odoo shell -d <db> < debug_4932498768A_v2.py
"""

print("=" * 100)
print("DEBUG v2: Tại sao Stock=550 thay vì 549?")
print("=" * 100)

product = env['product.product'].search([
    ('default_code', '=', '4932498768A'),
], limit=1)

print(f"\nProduct: {product.display_name} (id={product.id})")

# 1. Quant hiện tại chi tiết
print("\n[1] QUANT HIỆN TẠI")
for loc_name in ['TSN/Stock', 'TSN/Khu vực đóng gói', 'TSN/Out']:
    quants = env['stock.quant'].search([
        ('product_id', '=', product.id),
        ('location_id.complete_name', '=', loc_name),
    ])
    for q in quants:
        print(f"    {q.location_id.complete_name}: on_hand={q.quantity} | reserved={q.reserved_quantity} | available={q.available_quantity}")

# 2. PACK/08012 chi tiết
print("\n[2] PACK/08012 (S01434) - PICKING BỊ GIẢM QTY")
pack_08012 = env['stock.picking'].search([('name', '=', 'TSN/PACK/08012')], limit=1)
if pack_08012:
    print(f"    state={pack_08012.state}")
    for m in pack_08012.move_ids:
        print(f"    MOVE id={m.id} | product={m.product_id.display_name} | "
              f"state={m.state} | demand={m.product_uom_qty} | done/qty={m.quantity}")
        print(f"    move_line_ids count={len(m.move_line_ids)}")
        for ml in m.move_line_ids:
            print(f"      LINE id={ml.id} | state={ml.state} | qty={ml.quantity} | "
                  f"from={ml.location_id.complete_name} → to={ml.location_dest_id.complete_name}")
        if not m.move_line_ids:
            print(f"      !!! KHÔNG CÓ MOVE LINE → HÀNG ĐÃ BỊ UNRESERVE!")

    # Message history
    print(f"\n    MESSAGE LOG:")
    messages = env['mail.message'].search([
        ('res_id', '=', pack_08012.id),
        ('model', '=', 'stock.picking'),
    ], order='date asc', limit=20)
    for msg in messages:
        body = msg.body or ''
        if 'điều chỉnh' in body.lower() or 'tracking' in msg.message_type or msg.subtype_id:
            print(f"    [{msg.date}] type={msg.message_type} | subtype={msg.subtype_id.name if msg.subtype_id else 'N/A'}")
            if body:
                # Chỉ in nội dung text, bỏ HTML tag
                import re
                clean = re.sub('<[^>]+>', '', body)
                print(f"      {clean[:300]}")

# 3. Tính toán: on_hand lẽ ra phải là bao nhiêu?
print("\n[3] KIỂM CHỨNG SỐ LIỆU")

# Tổng tất cả quant TSN
tsn_quants = env['stock.quant'].search([
    ('product_id', '=', product.id),
    ('location_id.complete_name', 'ilike', 'TSN/'),
    ('location_id.complete_name', 'not ilike', 'TSNSR'),
    ('location_id.complete_name', 'not ilike', 'WLTSN'),
])
print(f"    Tất cả quant TSN (không TSNSR, WLTSN):")
total = 0
for q in tsn_quants:
    print(f"      {q.location_id.complete_name}: {q.quantity}")
    total += q.quantity
print(f"    TỔNG TSN: {total}")

# 4. Nếu PACK/08012 confirmed + done=0 + không có move_line
#    → đúng là hàng đã bị trả lại Stock
print("\n[4] KẾT LUẬN")
if pack_08012:
    move = pack_08012.move_ids.filtered(lambda m: m.product_id.id == product.id)
    if move and move[0].state == 'confirmed' and move[0].quantity == 0 and not move[0].move_line_ids:
        print("    >>> PACK/08012 ở state=confirmed, done=0, KHÔNG CÓ move_line")
        print("    >>> Hàng đã bị unreserve → trả ngược về TSN/Khu vực đóng gói quant")
        print("    >>> NHƯNG vì code button_validate đã giảm done=0 trước khi validate")
        print("    >>> nên picking KHÔNG done được → hàng kẹt")
        print()
        print("    DIỄN BIẾN:")
        print("    1. S01434 PICK done → 1 con Stock(552→551) → Đóng gói(0→1)")
        print("    2. S01431 PICK done → 1 con Stock(551→550) → Đóng gói(1→2)")
        print("    3. User validate PACK/08012 (S01434) → code thấy on_hand=2, other_reserved=1 (PACK/08013)")
        print("       → real_available = 2-1=1... NHƯNG lúc đó có thể on_hand chưa reflect đủ")
        print("       → code giảm done 1→0 → PACK/08012 kẹt confirmed")
        print("    4. Vì done=0, Odoo unreserve 1 con ở Đóng gói → Đóng gói giảm reserved")
        print("    5. S01431 PACK/08013 done → 1 con Đóng gói(2→1) → Out(0→1)")
        print("    6. S01432 PICK done → 1 con Stock(550→549... SAI! vẫn 550 vì bước 4 đã trả 1 con)")
        print("       → Stock thực tế: 552 - 3(pick) + 0(không unreserve vật lý, chỉ reserve) = 549")
        print()

# 5. Kiểm tra: có move nào khác làm tăng Stock không?
print("\n[5] CÓ MOVE NÀO KHÁC LÀM TĂNG TSN/STOCK TRONG NGÀY?")
from datetime import datetime
today_start = datetime(2026, 4, 2, 23, 0, 0)
today_end = datetime(2026, 4, 3, 23, 59, 59)

incoming_lines = env['stock.move.line'].search([
    ('product_id', '=', product.id),
    ('location_dest_id', '=', 1779),  # TSN/Stock id
    ('state', '=', 'done'),
    ('date', '>=', today_start),
    ('date', '<=', today_end),
], order='date asc')

for dl in incoming_lines:
    print(f"    INCOMING → Stock: line={dl.id} | picking={dl.picking_id.name} | "
          f"date={dl.date} | from={dl.location_id.complete_name} | qty={dl.quantity}")

outgoing_lines = env['stock.move.line'].search([
    ('product_id', '=', product.id),
    ('location_id', '=', 1779),  # TSN/Stock id
    ('state', '=', 'done'),
    ('date', '>=', today_start),
    ('date', '<=', today_end),
], order='date asc')

for dl in outgoing_lines:
    print(f"    OUTGOING Stock →: line={dl.id} | picking={dl.picking_id.name} | "
          f"date={dl.date} | to={dl.location_dest_id.complete_name} | qty={dl.quantity}")

in_total = sum(dl.quantity for dl in incoming_lines)
out_total = sum(dl.quantity for dl in outgoing_lines)
print(f"\n    Tổng VÀO Stock: {in_total}")
print(f"    Tổng RA Stock: {out_total}")
print(f"    Net Stock thay đổi: {in_total - out_total}")
print(f"    → Nếu ban đầu 552, hiện tại phải = 552 + {in_total} - {out_total} = {552 + in_total - out_total}")

actual_stock = env['stock.quant'].search([
    ('product_id', '=', product.id),
    ('location_id', '=', 1779),
], limit=1)
print(f"    → Thực tế TSN/Stock on_hand = {actual_stock.quantity if actual_stock else 'NOT FOUND'}")

if actual_stock and abs((552 + in_total - out_total) - actual_stock.quantity) > 0.001:
    print(f"    !!! SAI LỆCH: {actual_stock.quantity} != {552 + in_total - out_total}")
    print(f"    !!! Chênh lệch = {actual_stock.quantity - (552 + in_total - out_total)}")
else:
    print(f"    ✓ KHỚP! Số liệu đúng dựa trên done move lines")

print("\n" + "=" * 100)
print("XONG.")
print("=" * 100)
