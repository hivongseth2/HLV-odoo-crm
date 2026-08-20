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

section("Gọi lại đúng request thật (kho=3, pending_partial, limit=372, search rỗng)")
print(f"  kwargs: {KWARGS}")

# Chạy 2 lần liên tiếp: lần 1 có thể vẫn phải "làm nóng" cache location->warehouse
# (nếu server vừa restart), lần 2 mới phản ánh đúng tốc độ ổn định.
for i in (1, 2):
    t0 = time.time()
    res = env['sale.order'].get_delivery_dashboard_data(**KWARGS)
    t1 = time.time()
    print(f"  Lần {i}: {t1 - t0:.3f}s | total_count={res.get('total_count')} | orders_returned={len(res.get('orders', []))}")

section("XONG")
print("  Nếu lần 2 vẫn > 5s -> vấn đề không nằm ở tính toán Python/DB nữa, quay lại nghi ngờ")
print("  worker/connection contention trên Odoo.sh (nên so lại với Network tab TTFB cùng lúc).")
