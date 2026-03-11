# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID

# Tìm đơn hàng bị lỗi
order_name = 'ĐƠN HOÀN TIỀN POS CỬA HÀNG BẾN CAM/0051'
order = env['pos.order'].search([('name', '=', order_name)], limit=1)

if not order:
    print(f"FAILED: Order {order_name} not found")
else:
    print(f"ORDER: {order.name}")
    for line in order.lines:
        print(f"  LINE: {line.product_id.display_name} Qty: {line.qty}")
        if line.refunded_orderline_id:
            orig = line.refunded_orderline_id
            print(f"    Refunded from: {orig.order_id.name}")
            
            # Dump all pickings and moves for the original order
            print("    ORIGINAL ORDER STOCK DETAILS:")
            for p in orig.order_id.picking_ids:
                print(f"      Picking: {p.name} Type: {p.picking_type_id.name} State: {p.state}")
                for move in p.move_ids.filtered(lambda m: m.product_id == line.product_id):
                    print(f"        Move: {move.product_id.display_name} Qty: {move.product_uom_qty}")
                    print(f"          From: {move.location_id.complete_name} (Usage: {move.location_id.usage})")
                    print(f"          To:   {move.location_dest_id.complete_name} (Usage: {move.location_dest_id.usage})")
                    for ml in move.move_line_ids:
                        print(f"          ML: {ml.location_id.complete_name} -> {ml.location_dest_id.complete_name} Qty: {ml.quantity}")

    # Check if the module's override is actually seen
    import inspect
    try:
        method = env['stock.picking']._prepare_stock_move_vals
        source_file = inspect.getsourcefile(method)
        print(f"\nMETHOD OVERRIDE CHECK:")
        print(f"  _prepare_stock_move_vals source: {source_file}")
    except Exception as e:
        print(f"\nMETHOD OVERRIDE CHECK FAILED: {e}")
