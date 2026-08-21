# -*- coding: utf-8 -*-
"""
verify_packing_status_fix.py
=================================
Xác nhận fix packing_status trong delivery_planner_stock.py (bản 2 — sau khi user phản hồi
bản 1 chưa đúng): khi đơn có 1 lô ĐÃ đóng gói xong (PACK done) đang chờ ở OUT (CHƯA giao),
dù đơn còn 1 lô KHÁC (backorder PICK) đang chờ lấy/đóng gói riêng do thiếu hàng, thì
packing_status phải là 'fully_packed' (FE hiển thị "Đã Gói, Chờ Nhận Giao") — không phải
'waiting_stock' hay 'unpacked' như trước, vì phần đã sẵn sàng cần được đẩy đi giao ngay,
không nên bị "che" bởi phần backorder còn thiếu hàng.

3 đơn kiểm tra (đổi ORDER_NAMES nếu cần):
  - DH125524949234879: PICK/10836 done -> PACK/07777 done -> OUT/12362 assigned (chưa giao);
    PICK/11533 confirmed (backorder, dòng T48A-3C-A-HANYOUNG thực sự hết hàng).
    Kỳ vọng: packing_status == 'fully_packed'.
  - DH125524949235568: PICK/11486 done -> PACK/07778 done (36/50) -> OUT/12363 assigned
    (chưa giao); PICK/11534 confirmed (backorder 14 còn thiếu hàng).
    Kỳ vọng: packing_status == 'fully_packed'.
  - DH125524949235617: PICK/11496 done+đã in -> PACK/07773 "Sẵn sàng" (active, chưa done);
    PICK/11528 confirmed, CHƯA in (backorder cắt ngang từ PICK/11496, chờ hàng).
    Kỳ vọng: packing_status == 'unpacked' (PACK chưa done nên đúng là chưa đóng gói xong)
    NHƯNG has_active_pick_printed phải là True (để FE hiển thị "Đã In, Chờ Đóng Gói" thay vì
    "Có Hàng Chưa Đóng Gói" chung) — trước fix bug thứ 2 này luôn ra False vì active_pick_flows
    (PICK/11528 chưa in) che mất PACK/07773 đang active với done-PICK/11496 đã in.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/verify_packing_status_fix.py
"""

ORDER_NAMES = ["DH125524949234879", "DH125524949235568", "DH125524949235617"]  # đổi nếu cần
EXPECTED = {
    "DH125524949234879": {"packing_status": "fully_packed"},
    "DH125524949235568": {"packing_status": "fully_packed"},
    "DH125524949235617": {"packing_status": "unpacked", "has_active_pick_printed": True},
}

SEP = "=" * 100
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

Service = env['hlv.delivery.planner.service'].sudo()

for order_name in ORDER_NAMES:
    so = env['sale.order'].sudo().search([('name', '=', order_name)], limit=1)
    if not so:
        section(f"Không tìm thấy đơn {order_name!r}")
        continue

    section(f"Đơn {so.name} (id={so.id}, state={so.state})")

    print("  -- Từng dòng bán hàng (sale.order.line) --")
    for sol in so.order_line:
        if not sol.product_id or sol.product_id.type == 'service':
            continue
        print(
            f"  line #{sol.id:>6} {sol.product_id.display_name[:35]:35s} "
            f"qty_ord={sol.product_uom_qty:>7.2f} qty_del={sol.qty_delivered:>7.2f}"
        )

    print("\n  -- Phiếu (stock.picking) --")
    for p in so.picking_ids.sorted('id'):
        print(
            f"  {p.name:20s} seq_code={p.picking_type_id.sequence_code or '':6s} "
            f"state={p.state:10s} x_printed={getattr(p, 'x_printed', '?')!s:6s}"
        )

    _s, _mids, _stats, _avail, _onhand, status_by_so = Service._calculate_po_and_stock_status(
        so, po_date_from='', po_date_to='', po_status='all',
        filter_delivery_status='all', filter_stock_status='all', filter_packing_status='all',
        show_completed=True, filter_need_transfer=False, filter_new_orders=False,
    )
    live = status_by_so.get(so.id, {})
    print(f"\n  stock_status={live.get('stock_status')!r}  packing_status={live.get('packing_status')!r}  "
          f"has_active_pick_printed={live.get('has_active_pick_printed')!r}")
    print(f"  Toàn bộ dict: {live}")

    expected = EXPECTED.get(order_name, {})
    for k, expected_v in expected.items():
        actual_v = live.get(k)
        print(f"  KỲ VỌNG {k} == {expected_v!r} -> "
              f"{'OK' if actual_v == expected_v else f'CHƯA ĐÚNG (thực tế={actual_v!r})'}")

section("XONG")
