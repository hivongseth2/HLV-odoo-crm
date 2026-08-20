# -*- coding: utf-8 -*-
"""
profile_cold_start_full.py
=============================
Sau khi fix pack_sequence (hlv_pack_sequence) + prefetch warm-up (_batch_transfer_suggestions),
UI giảm còn ~9.24s (Network tab: Waiting for server response = 9.10s, KHÔNG phải do
queueing/frontend — Queueing chỉ 2.62ms). Vẫn còn ~9s backend chưa giải thích được — nghi ngờ
còn 1 (hoặc vài) field/hàm khác bị tính lại tốn kém mỗi request, giống kiểu bug pack_sequence
cũ (non-stored compute field không batch, chỉ lộ ra ở LẦN GỌI ĐẦU của 1 process/env mới).

Script này cProfile TOÀN BỘ get_delivery_dashboard_data() trong 1 lần gọi duy nhất (không
tách bước) để tìm ra hotspot còn lại — bất kể nằm ở module nào (kể cả module khác, giống
lần trước tìm ra hlv_pack_sequence).

CHỈ ĐỌC — không write/create/unlink gì.

QUAN TRỌNG: phải chạy trên shell MỚI (chưa gọi gì từ module delivery planner trước đó trong
process này), nếu không sẽ bắt trúng lúc đã "nóng" và không thấy gì.

Chạy bằng lệnh (PHẢI là shell MỚI):
    python odoo-bin shell -d <TEN_DATABASE> < bin/profile_cold_start_full.py
"""

import cProfile
import pstats
import io
import time

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

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
    limit=373,
    offset=0,
    include_stats=False,
)

section("cProfile TOÀN BỘ get_delivery_dashboard_data() — LẦN GỌI ĐẦU TIÊN trong process này")

profiler = cProfile.Profile()
t0 = time.time()
profiler.enable()
res = env['sale.order'].get_delivery_dashboard_data(**KWARGS)
profiler.disable()
t1 = time.time()
print(f"  Tổng thời gian: {t1 - t0:.3f}s | total_count={res.get('total_count')}")

section("Top 40 theo cumulative time")
buf = io.StringIO()
pstats.Stats(profiler, stream=buf).sort_stats('cumulative').print_stats(40)
print(buf.getvalue())

section("Top 25 theo tottime (thời gian THUẦN trong chính hàm đó)")
buf2 = io.StringIO()
pstats.Stats(profiler, stream=buf2).sort_stats('tottime').print_stats(25)
print(buf2.getvalue())

section("XONG — tìm dòng nào KHÔNG thuộc odoo/*.py core (custom_addons/...) có cumtime/tottime lớn")
