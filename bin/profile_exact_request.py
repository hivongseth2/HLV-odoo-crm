# -*- coding: utf-8 -*-
"""
profile_exact_request.py
==========================
Gọi lại CHÍNH XÁC request get_delivery_dashboard_data mà user vừa chụp từ
DevTools (kho id=3, filter_delivery_status=pending_partial, limit=372, không
search) để đo thời gian thật SAU KHI đã deploy các fix:
  - coalescing lock phía client (không còn dồn request)
  - hook dirty theo sản phẩm khi move done/assign/unreserve (thay reset toàn bộ
    snapshot mỗi ngày)
  - bỏ yêu cầu snapshot_date == today khỏi fast-path
  - cache location->warehouse (_get_loc_to_wh_map)

CHỈ ĐỌC — không write/create/unlink gì, an toàn chạy trên DB thật.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/profile_exact_request.py
"""

import time

# Kwargs copy nguyên từ payload DevTools user gửi (null -> '' cho các field string)
KWARGS = dict(
    search_query='',
    filter_warehouse_id='3',
    filter_delivery_status='pending_partial',
    filter_stock_status='all',
    filter_date_from='',
    filter_date_to='',
    filter_done_date_from='',
    filter_done_date_to='',
    filter_po_date_from='',
    filter_po_date_to='',
    filter_po_status='all',
    filter_packing_status='all',
    filter_saler_code='',
    filter_htgh='',
    filter_delivery_type='all',
    filter_tag_ids='',
    show_completed=False,
    filter_need_transfer=False,
    filter_new_orders=False,
    filter_print_status='all',
    filter_shipper_received='all',
    limit=372,
    offset=0,
    include_stats=False,
)

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

section("A) Chạy bằng user MẶC ĐỊNH của shell (thường là superuser/OdooBot — BỎ QUA ir.rule)")
print(f"  env.user hiện tại: {env.user.name!r} (uid={env.user.id}, is superuser={env.user._is_superuser()})")
for i in (1, 2):
    t0 = time.time()
    res = env['sale.order'].get_delivery_dashboard_data(**KWARGS)
    t1 = time.time()
    print(f"  Lần {i}: {t1 - t0:.3f}s | total_count={res.get('total_count')} | orders_returned={len(res.get('orders', []))}")

section("B) Chạy ĐÚNG bằng user thật của request (uid=2, có áp ir.rule/record rules)")
real_user_env = env(user=2)
real_user = real_user_env.user
print(f"  Chạy với user: {real_user.name!r} (uid={real_user.id}, is superuser={real_user._is_superuser()})")
for i in (1, 2):
    t0 = time.time()
    res = real_user_env['sale.order'].get_delivery_dashboard_data(**KWARGS)
    t1 = time.time()
    print(f"  Lần {i}: {t1 - t0:.3f}s | total_count={res.get('total_count')} | orders_returned={len(res.get('orders', []))}")

section("XONG")
print("  So sánh A) vs B): nếu B) chậm hẳn so với A) (kể cả lần 2, đã 'warm') -> đúng là do")
print("  ir.rule/record rules áp cho user thật (uid=2), không phải cold-cache hay worker nữa —")
print("  cần xem lại rule/domain phân quyền trên sale.order (và các model liên quan) đang nặng ở đâu.")
