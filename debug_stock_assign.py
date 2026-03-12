"""
Debug script để kiểm tra tại sao action_assign() không hoạt động
Chạy trong Odoo console hoặc Django shell
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'odoo.settings')
django.setup()

from odoo import api, models
from odoo.addons.stock.models.stock_move import StockMove

# 1. Lấy picking order bị lỗi (thay picking_id)
picking_id = 'KBC/PICK/02762'  # Thay bằng ID thực tế
picking = env['stock.picking'].search([('name', '=', picking_id)], limit=1)

if not picking:
    print(f"❌ Không tìm thấy picking: {picking_id}")
    exit()

print(f"✅ Tìm thấy picking: {picking.name}")
print(f"   Trạng thái: {picking.state}")
print(f"   Total moves: {len(picking.move_lines)}")
print()

# 2. Kiểm tra từng move
for i, move in enumerate(picking.move_lines, 1):
    print(f"--- MOVE #{i}: {move.name} ---")
    print(f"   Product: {move.product_id.display_name}")
    print(f"   Qty: {move.product_uom_qty} {move.product_uom.name}")
    print(f"   From: {move.location_id.display_name}")
    print(f"   To: {move.location_dest_id.display_name}")
    print(f"   State: {move.state}")
    print()
    
    # 3. Kiểm tra stock quant tại vị trí từ
    quants = env['stock.quant'].search([
        ('product_id', '=', move.product_id.id),
        ('location_id', '=', move.location_id.id),
    ])
    
    if not quants:
        print(f"   ⚠️  KHÔNG CÓ QUANT tại {move.location_id.display_name}!")
        
        # Kiểm tra quant ở những nơi khác
        all_quants = env['stock.quant'].search([
            ('product_id', '=', move.product_id.id),
        ])
        if all_quants:
            print(f"   💡 NHƯNG sản phẩm này có ở những nơi khác:")
            for q in all_quants:
                print(f"      - {q.location_id.display_name}: {q.quantity} {q.product_uom.name} (reserved: {q.reserved_quantity})")
    else:
        for q in quants:
            print(f"   ✅ QUANT tìm thấy:")
            print(f"      Quantity: {q.quantity}")
            print(f"      Reserved: {q.reserved_quantity}")
            print(f"      Available: {q.available_quantity}")
            print(f"      Inventory Quantity: {q.inventory_quantity}")
    
    print()
    
    # 4. Kiểm tra move lines
    if move.move_line_ids:
        print(f"   Move lines ({len(move.move_line_ids)}):")
        for ml in move.move_line_ids:
            print(f"      - Qty: {ml.quantity}, Qty Done: {ml.qty_done}")
    else:
        print(f"   ⚠️  KHÔNG CÓ MOVE LINE!")
    
    print()

# 5. Thử assign theo cách thủ công
print("=" * 50)
print("THỬ ASSIGN THEO LÝ THUYẾT:")
print("=" * 50)

# Kiểm tra từng move
failed_moves = []
for move in picking.move_lines:
    try:
        move._action_assign()
        print(f"✅ {move.name}: Assign thành công -> {move.state}")
    except Exception as e:
        print(f"❌ {move.name}: Lỗi assign -> {str(e)[:100]}")
        failed_moves.append((move, str(e)))

print()

# 6. Nếu có lỗi, debug chi tiết
if failed_moves:
    print("=" * 50)
    print("CHI TIẾT LỖI:")
    print("=" * 50)
    for move, error in failed_moves:
        print(f"\n❌ {move.name}:")
        print(f"   Location from: {move.location_id.id} ({move.location_id.display_name})")
        print(f"   Location to: {move.location_dest_id.id} ({move.location_dest_id.display_name})")
        print(f"   Error: {error}")
        
        # Try get_available_quantity
        try:
            qty = move.product_id.with_context({
                'location': move.location_id.id,
            }).qty_available
            print(f"   Qty Available at location: {qty}")
        except:
            pass

print("\n✅ Debug hoàn tất!")
print("\nGợi ý:")
print("1. Kiểm tra xem quant có tồn tại không?")
print("2. Kiểm tra location từ có đúng không?")
print("3. Có bao nhiêu quant đã bị reserved?")
