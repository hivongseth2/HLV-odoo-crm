#!/usr/bin/env python3
"""
Debug script: Phân tích tình trạng stock cho picking KBC/PICK/02820
Chạy: odoo-bin shell -d <database> < debug_pick02820.py
Hoặc paste vào Odoo shell interactive
"""

PICKING_NAME = 'KBC/PICK/02820'
PRODUCT_REF = 'AK-8148'

print("=" * 70)
print(f"DEBUG: {PICKING_NAME} | product containing '{PRODUCT_REF}'")
print("=" * 70)

# 1. Lấy picking
picking = env['stock.picking'].search([('name', '=', PICKING_NAME)], limit=1)
if not picking:
    print(f"KHÔNG TÌM THẤY picking {PICKING_NAME}")
else:
    print(f"Picking: {picking.name} | state={picking.state}")
    print(f"Location src: {picking.location_id.display_name} (id={picking.location_id.id})")
    print()

    for move in picking.move_ids:
        if PRODUCT_REF.upper() not in move.product_id.default_code.upper():
            continue

        product = move.product_id
        location = move.location_id
        print(f"MOVE: {product.display_name}")
        print(f"  demand={move.product_uom_qty} | state={move.state}")
        print()

        # 2. Quants tại location (bao gồm sub-locations)
        quants = env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', 'child_of', location.id),
        ])
        print("--- QUANTS (stock.quant) ---")
        total_on_hand = 0
        total_reserved_quant = 0
        for q in quants:
            print(f"  location={q.location_id.display_name} (id={q.location_id.id})")
            print(f"    on_hand={q.quantity} | reserved={q.reserved_quantity} | available={q.available_quantity}")
            total_on_hand += q.quantity
            total_reserved_quant += q.reserved_quantity
        print(f"  TOTAL: on_hand={total_on_hand} | reserved_in_quant={total_reserved_quant} | available={total_on_hand - total_reserved_quant}")
        print()

        # 3. ALL active move lines cho product này tại location
        all_mls = env['stock.move.line'].search([
            ('product_id', '=', product.id),
            ('location_id', 'child_of', location.id),
            ('state', 'not in', ['done', 'cancel']),
        ])
        print("--- MOVE LINES (stock.move.line) active ---")
        total_ml_qty = 0
        for ml in all_mls:
            is_current = ml.picking_id.id == picking.id
            marker = "<<< THIS PICKING" if is_current else ""
            print(f"  ml_id={ml.id} | picking={ml.picking_id.name} | location={ml.location_id.display_name}")
            print(f"    qty={ml.quantity} | state={ml.state} {marker}")
            total_ml_qty += ml.quantity
        print(f"  TOTAL qty across all move lines: {total_ml_qty}")
        print()

        # 4. So sánh
        this_pick_ml_qty = sum(ml.quantity for ml in all_mls if ml.picking_id.id == picking.id)
        other_pick_ml_qty = sum(ml.quantity for ml in all_mls if ml.picking_id.id != picking.id)
        print("--- PHÂN TÍCH ---")
        print(f"  on_hand (quant):            {total_on_hand}")
        print(f"  reserved_in_quant:          {total_reserved_quant}")
        print(f"  sum(move_lines.qty) total:  {total_ml_qty}")
        print(f"    - THIS picking:           {this_pick_ml_qty}")
        print(f"    - OTHER pickings:         {other_pick_ml_qty}")
        ghost = total_reserved_quant - total_ml_qty
        print(f"  GHOST reservation (quant - lines): {ghost}")
        print()
        print(f"  --> max_allowed theo quant logic:      {total_on_hand - total_reserved_quant + this_pick_ml_qty}")
        print(f"  --> max_allowed theo move_line logic:  {total_on_hand - other_pick_ml_qty}")

print("=" * 70)
