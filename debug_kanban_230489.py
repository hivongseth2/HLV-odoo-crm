#!/usr/bin/env python3
"""
Debug: Tại sao đơn 230489 không hiện trên kanban?
Chạy: odoo shell < debug_kanban_230489.py
"""
import logging
_logger = logging.getLogger(__name__)

SEARCH_TERM = '230489'

print("=" * 80)
print(f"DEBUG: Tìm đơn chứa '{SEARCH_TERM}' và kiểm tra trạng thái kanban")
print("=" * 80)

# 1. Tìm SO
sos = env['sale.order'].search([('name', 'ilike', SEARCH_TERM)], limit=5)
if not sos:
    print(f"[ERROR] Không tìm thấy đơn hàng nào chứa '{SEARCH_TERM}'")
    exit()

for so in sos:
    print(f"\n{'─' * 60}")
    print(f"SO: {so.name} (id={so.id})")
    print(f"  State: {so.state}")
    print(f"  x_picking_slip_printed: {so.x_picking_slip_printed}")
    print(f"  Commitment date: {so.commitment_date}")
    print(f"  Warehouse: {so.warehouse_id.name} (id={so.warehouse_id.id})")

    # 2. Pickings
    print(f"\n  === PICKINGS ({len(so.picking_ids)}) ===")
    active_outflow = env['stock.picking']
    for p in so.picking_ids:
        is_return = bool(p.return_id)
        is_outflow = p.picking_type_code in ('outgoing', 'internal')
        is_active = p.state not in ('done', 'cancel') and is_outflow and not is_return
        shipper_info = ""
        if hasattr(p, 'shipper_received'):
            shipper_info = (
                f"  shipper_received={p.shipper_received}"
                f"  shipper_returned={p.shipper_returned}"
                f"  shipper_receive_time={p.shipper_receive_time}"
            )
        printed_info = f"  x_printed={p.x_printed}" if hasattr(p, 'x_printed') else ""
        print(f"  [{p.name}] state={p.state} type={p.picking_type_code} "
              f"seq={p.picking_type_id.sequence_code} "
              f"return={is_return} active_outflow={is_active}"
              f"{shipper_info}{printed_info}")
        if is_active:
            active_outflow |= p

    print(f"\n  Active outflow count: {len(active_outflow)}")

    # 3. has_shipper_received
    has_shipper_received = any(
        p.shipper_received and not p.shipper_returned
        for p in active_outflow
        if p.picking_type_code == 'outgoing'
    )
    print(f"  has_shipper_received: {has_shipper_received}")

    # Nếu picking đã done mà shipper_received = True → picking ra khỏi active_outflow
    done_outgoing_with_shipper = so.picking_ids.filtered(
        lambda p: p.state == 'done'
        and p.picking_type_code == 'outgoing'
        and not p.return_id
        and hasattr(p, 'shipper_received')
        and p.shipper_received
        and not p.shipper_returned
    )
    if done_outgoing_with_shipper:
        print(f"  [!!!] CÓ {len(done_outgoing_with_shipper)} picking DONE mà shipper_received=True:")
        for p in done_outgoing_with_shipper:
            print(f"       {p.name} state={p.state} shipper_received={p.shipper_received}")
        print(f"       → Picking đã DONE nên bị loại khỏi active_outflow")
        print(f"       → has_shipper_received = False dù tài xế đã nhận!")

    # 4. has_new_unprinted_pickings
    has_new_unprinted_pickings = (
        bool(so.x_picking_slip_printed)
        and bool(active_outflow)
        and any(
            not p.x_printed
            for p in active_outflow
            if 'PICK' in (p.picking_type_id.sequence_code or '').upper()
        )
    )
    print(f"  has_new_unprinted_pickings: {has_new_unprinted_pickings}")

    # 5. Packing status
    has_pending = False
    total_avail = 0
    packed_qty = 0

    for line in so.order_line:
        if line.display_type or not line.product_id:
            continue
        # Odoo 18: service và kit bỏ qua, consu (storable) tính
        p_type = line.product_id.type
        if p_type == 'service':
            continue
        pending = line.product_uom_qty - line.qty_delivered
        if pending > 0:
            has_pending = True

    # packed_qty from move lines
    for p in active_outflow:
        for ml in p.move_line_ids:
            if ml.result_package_id:
                packed_qty += ml.quantity

    # Simplified avail check (just check if any pending)
    print(f"\n  === PACKING ANALYSIS ===")
    print(f"  has_pending (undelivered lines): {has_pending}")
    print(f"  packed_qty (in packages): {packed_qty}")

    has_any_outflow = any(
        p.picking_type_code in ('outgoing', 'internal') and not p.return_id
        for p in so.picking_ids
    )
    no_active_outflow = has_any_outflow and not bool(active_outflow)
    is_returned_or_stopped = no_active_outflow and so.delivery_status != 'full'

    print(f"  has_any_outflow: {has_any_outflow}")
    print(f"  no_active_outflow: {no_active_outflow}")
    print(f"  is_returned_or_stopped: {is_returned_or_stopped}")

    # 6. Delivery status
    delivered_qty_total = sum(l.qty_delivered for l in so.order_line
                              if not l.display_type and l.product_id and l.product_id.type != 'service')
    ordered_qty_total = sum(l.product_uom_qty for l in so.order_line
                             if not l.display_type and l.product_id and l.product_id.type != 'service')
    if ordered_qty_total > 0:
        if delivered_qty_total >= ordered_qty_total:
            real_delivery_status = 'full'
        elif delivered_qty_total > 0:
            real_delivery_status = 'partial'
        else:
            real_delivery_status = 'unshipped'
    else:
        real_delivery_status = 'unshipped'
    print(f"  real_delivery_status: {real_delivery_status} (delivered={delivered_qty_total}/{ordered_qty_total})")

    # 7. Simulate JS column assignment
    print(f"\n  === JS KANBAN COLUMN SIMULATION (packing_status) ===")

    # Backend packing_status
    packing_status = so_packing = 'unknown'
    if not has_pending:
        packing_status = 'delivered'
    elif not active_outflow:
        packing_status = 'waiting_stock'  # simplified
    else:
        if packed_qty > 0:
            packing_status = 'fully_packed'  # simplified: needs total_avail comparison
        else:
            packing_status = 'unpacked'

    print(f"  Backend packing_status (approx): {packing_status}")

    # Simulate JS logic
    val = packing_status
    reason = f"Original val = '{val}'"

    if real_delivery_status == 'full':
        reason = "real_delivery_status === 'full' → EXCLUDED from packing view entirely!"
        val = None
    elif is_returned_or_stopped:
        reason = "is_returned_or_stopped → EXCLUDED (shown in 'Trả hàng')"
        val = None
    elif has_shipper_received:
        val = 'shipping'
        reason = "has_shipper_received → 'shipping'"
    elif has_new_unprinted_pickings:
        val = 'has_unprinted'
        reason = "has_new_unprinted_pickings → 'has_unprinted'"
    elif val == 'fully_packed':
        val = 'packed_waiting_ship'
        reason = "fully_packed → 'packed_waiting_ship' (FIXED)"
    elif so.x_picking_slip_printed:
        val = 'printed_waiting'
        reason = "x_picking_slip_printed → 'printed_waiting'"
    elif val == 'partial_packed':
        val = 'unpacked'
        reason = "partial_packed → 'unpacked'"

    columns = ['waiting_stock', 'unpacked', 'has_unprinted', 'printed_waiting', 'packed_waiting_ship', 'shipping']
    matched = val in columns if val else False

    print(f"  Final val: '{val}'")
    print(f"  Reason: {reason}")
    print(f"  Matches any column? {matched}")
    if not matched:
        print(f"  ❌ ĐƠN NÀY SẼ BIẾN MẤT KHỎI KANBAN!")
        print(f"     Available columns: {columns}")

    print()

print("=" * 80)
print("KẾT LUẬN:")
print("Bug 1 (JS): fully_packed không map sang packed_waiting_ship → đơn mất khỏi kanban")
print("  FIX: else if (val === 'fully_packed') val = 'packed_waiting_ship';")
print("Bug 2 (Backend): effective_packing giữ 'fully_packed' thay vì 'packed_waiting_ship'")
print("  → Filter theo 'Đã gói, chờ nhận giao' cũng không tìm được")
print("  FIX: effective_packing = 'packed_waiting_ship' khi packing_status == 'fully_packed'")
print("Bug 3 (Script): product_id.type != 'product' sai cho Odoo 18")
print("  Odoo 18 dùng type='consu' cho storable, script đã fix dùng type != 'service'")
print("=" * 80)
