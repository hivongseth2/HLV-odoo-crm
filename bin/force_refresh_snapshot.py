# -*- coding: utf-8 -*-
"""
force_refresh_snapshot.py
============================
Đơn DH125524949234744 bị kẹt ở packing_status cũ (Kanban không nhảy cột) do lỗ hổng hook
(stock.picking thiếu create(), stock.move thiếu picking_id trong field theo dõi) — ĐÃ SỬA để
không lặp lại, nhưng snapshot của đơn NÀY đã bị stale từ TRƯỚC khi fix, cần refresh tay ngay
để xác nhận fix có tác dụng, không cần chờ hook mới trigger lần tới.

Đánh dấu dirty rồi GỌI LUÔN cron refresh cho đúng đơn này (không đợi cron mỗi phút) — in ra
packing_status trước/sau để xác nhận đã đổi đúng.

CHỈ ghi vào bảng snapshot (không đụng gì tới sale.order/stock.picking thật).

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/force_refresh_snapshot.py
"""

ORDER_NAME = "DH125524949234744"  # đổi nếu cần

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

so = env['sale.order'].sudo().search([('name', '=', ORDER_NAME)], limit=1)
if not so:
    print(f"  Không tìm thấy đơn {ORDER_NAME!r}")
else:
    Snapshot = env['hlv.delivery.planner.snapshot'].sudo()
    snap = Snapshot.search([('sale_order_id', '=', so.id)], limit=1)

    section(f"TRƯỚC khi refresh — đơn {so.name} (id={so.id})")
    if snap:
        print(f"  snapshot #{snap.id}: dirty={snap.dirty} snapshot_date={snap.snapshot_date} "
              f"packing_status={snap.packing_status!r} stock_status={snap.stock_status!r} "
              f"has_assigned_pick={snap.has_assigned_pick}")
    else:
        print("  Chưa có snapshot cho đơn này.")

    Snapshot.mark_dirty_for_sale_orders([so.id], reason='manual_force_refresh')
    Service = env['hlv.delivery.planner.service'].sudo()
    _s, _mids, _stats, _avail, _onhand, status_by_so = Service._calculate_po_and_stock_status(
        so, po_date_from='', po_date_to='', po_status='all',
        filter_delivery_status='all', filter_stock_status='all', filter_packing_status='all',
        show_completed=True, filter_need_transfer=False, filter_new_orders=False,
    )
    Snapshot.upsert_from_status_data(so, status_by_so)
    env.cr.commit()

    snap = Snapshot.search([('sale_order_id', '=', so.id)], limit=1)
    section("SAU khi refresh")
    print(f"  snapshot #{snap.id}: dirty={snap.dirty} snapshot_date={snap.snapshot_date} "
          f"packing_status={snap.packing_status!r} stock_status={snap.stock_status!r} "
          f"has_assigned_pick={snap.has_assigned_pick}")
    print(f"\n  status_by_so trả về trực tiếp từ tính live: {status_by_so.get(so.id)}")

section("XONG")
print("  F5 lại dashboard backend — đơn này giờ phải hiện đúng cột Kanban theo packing_status mới.")
