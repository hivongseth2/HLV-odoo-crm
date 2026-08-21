# -*- coding: utf-8 -*-
"""
check_packing_status_live_vs_snapshot.py
============================================
Đơn DH125524949234879: có PICK/10836 đã "Hoàn tất" (đã đóng gói xong qua PACK/07777) và
PICK/11533 vẫn "Chưa in" (backorder, còn active) — Kanban vẫn kẹt ở "Có Hàng Chưa Đóng Gói"
dù đã deploy fix hook create() lần trước.

Cần phân biệt 2 khả năng:
  (A) Snapshot vẫn đang trả giá trị CŨ (khác với tính LIVE ngay bây giờ) -> vẫn còn 1 lỗ hổng
      hook khác chưa bắt được (fix trước chưa đủ / chưa deploy / cron chưa refresh).
  (B) Snapshot và tính LIVE ra CÙNG 1 giá trị 'unpacked' -> KHÔNG phải bug cache — đây là ĐÚNG
      hành vi thiết kế: "còn PICK active (backorder) thì chưa tính fully_packed dù PACK khác
      đã done" (xem delivery_planner_stock.py, comment "Nếu còn phiếu PICK đang active...").
      Nếu đúng case (B), vấn đề nằm ở KỲ VỌNG hành vi, không phải bug kỹ thuật.

Script in ra: state/x_printed của từng phiếu, giá trị packing_status TỪ SNAPSHOT (cache) so
với TỪ TÍNH LIVE (gọi lại đúng hàm _calculate_po_and_stock_status ngay bây giờ).

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_packing_status_live_vs_snapshot.py
"""

ORDER_NAME = "DH125524949234879"  # đổi nếu cần

SEP = "=" * 100
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

so = env['sale.order'].sudo().search([('name', '=', ORDER_NAME)], limit=1)
if not so:
    print(f"  Không tìm thấy đơn {ORDER_NAME!r}")
else:
    section(f"Đơn {so.name} (id={so.id}, state={so.state})")

    print("  -- Chi tiết từng phiếu (stock.picking) --")
    for p in so.picking_ids.sorted('id'):
        print(
            f"  {p.name:20s} type={p.picking_type_id.name or '':25s} "
            f"seq_code={p.picking_type_id.sequence_code or '':6s} state={p.state:10s} "
            f"x_printed={getattr(p, 'x_printed', '?')!s:6s} return_id={bool(p.return_id)}"
        )

    Snapshot = env['hlv.delivery.planner.snapshot'].sudo()
    snap = Snapshot.search([('sale_order_id', '=', so.id)], limit=1)
    section("Giá trị TỪ SNAPSHOT (cache đang hiển thị lên Kanban)")
    if snap:
        print(f"  dirty={snap.dirty}  snapshot_date={snap.snapshot_date}  "
              f"logic_version={snap.logic_version!r}")
        print(f"  packing_status={snap.packing_status!r}  stock_status={snap.stock_status!r}  "
              f"real_delivery_status={snap.real_delivery_status!r}")
        print(f"  has_active_pick_printed={snap.has_active_pick_printed}  "
              f"has_assigned_pick={snap.has_assigned_pick}  "
              f"has_shipper_received={snap.has_shipper_received}  "
              f"has_delivered_today={snap.has_delivered_today}")
    else:
        print("  Chưa có snapshot cho đơn này.")

    section("Giá trị TÍNH LIVE ngay bây giờ (gọi lại _calculate_po_and_stock_status)")
    Service = env['hlv.delivery.planner.service'].sudo()
    _s, _mids, _stats, _avail, _onhand, status_by_so = Service._calculate_po_and_stock_status(
        so, po_date_from='', po_date_to='', po_status='all',
        filter_delivery_status='all', filter_stock_status='all', filter_packing_status='all',
        show_completed=True, filter_need_transfer=False, filter_new_orders=False,
    )
    live = status_by_so.get(so.id, {})
    print(f"  {live}")

    section("SO SÁNH")
    if snap:
        keys = ['stock_status', 'packing_status', 'real_delivery_status', 'has_active_pick_printed',
                'has_assigned_pick', 'has_shipper_received', 'has_delivered_today']
        diffs = [k for k in keys if getattr(snap, k) != live.get(k)]
        if diffs:
            print(f"  KHÁC NHAU ở: {diffs} -> (A) snapshot đang stale, cần refresh/tìm hook còn thiếu.")
            for k in diffs:
                print(f"    {k}: snapshot={getattr(snap, k)!r}  live={live.get(k)!r}")
        else:
            print("  GIỐNG NHAU HOÀN TOÀN -> (B) không phải bug cache. packing_status='unpacked' là")
            print("  ĐÚNG theo thiết kế hiện tại: còn PICK/11533 đang active (backorder chưa xử lý)")
            print("  nên chưa được tính 'fully_packed' dù PACK/07777 khác đã hoàn tất.")
    else:
        print("  Không có snapshot để so sánh — chỉ có giá trị live ở trên.")
