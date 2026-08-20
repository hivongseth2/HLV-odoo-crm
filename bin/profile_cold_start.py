# -*- coding: utf-8 -*-
"""
profile_cold_start.py
=======================
Đã xác nhận: LẦN GỌI ĐẦU TIÊN trong 1 process odoo-bin shell MỚI luôn ra ~1571 query/12s cho
_fetch_packages_for_sales + _batch_transfer_suggestions, nhưng lần gọi THỨ HAI (cùng process)
chỉ 40 query/2.7s — một thứ gì đó được tính/nạp CHỈ 1 LẦN mỗi process rồi giữ mãi trong RAM,
và lần tính đầu đó rất tốn. Rất có thể đây là nguyên nhân UI "luôn chậm" nếu Odoo.sh tái tạo/
thu hồi worker process thường xuyên trên staging ít traffic (mỗi request thật rơi vào đúng
"lần đầu" của 1 worker mới).

Script này PHẢI chạy trên 1 shell MỚI (process chưa gọi get_delivery_dashboard_data lần nào) —
dùng cProfile để bắt CHÍNH XÁC cái gì đang được tính lần đầu trong 4c/7, giúp biết có warm-up
được không.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (PHẢI là shell MỚI, chưa chạy gì khác trước đó):
    python odoo-bin shell -d <TEN_DATABASE> < bin/profile_cold_start.py
"""

import cProfile
import pstats
import io

service = env['hlv.delivery.planner.service'].sudo()

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

WAREHOUSE_ID = '3'
FILTER_DELIVERY_STATUS = 'pending_partial'
LIMIT = 373
OFFSET = 0

section("Chuẩn bị input (search + snapshot + calculate_po_and_stock_status) — KHÔNG profile bước này")

search_domain = service._build_search_domain(
    '', WAREHOUSE_ID, FILTER_DELIVERY_STATUS, '', '',
    filter_saler_code='', filter_htgh='', filter_delivery_type='all',
    filter_tag_ids='', filter_mine=False,
)
sales = env['sale.order'].search(
    search_domain,
    order='x_studio_misa_order_date desc nulls last, create_date desc, '
          'commitment_date asc, date_order desc'
)
can_use = service._can_use_snapshot_dashboard_match(
    filter_po_date_from='', filter_po_date_to='', filter_po_status='all',
    filter_done_date_from='', filter_done_date_to='', filter_need_transfer=False, domain=None,
)
snapshot_match = service._get_snapshot_dashboard_match(
    sales, filter_delivery_status=FILTER_DELIVERY_STATUS, filter_stock_status='all',
    filter_packing_status='all', show_completed=False, filter_new_orders=False,
    filter_print_status='all', filter_shipper_received='all',
) if can_use else None

if snapshot_match:
    matched_ids = snapshot_match['matched_ids']
    page_sales = env['sale.order'].browse(matched_ids[OFFSET:OFFSET + LIMIT])
    page_sales, _pids, _stats, product_availabilities, product_on_hand, so_status_dict = \
        service._calculate_po_and_stock_status(
            page_sales, '', '', 'all', FILTER_DELIVERY_STATUS, 'all', 'all',
            show_completed=True, filter_need_transfer=False, filter_new_orders=False,
            filter_done_date_from='', filter_done_date_to='',
            filter_print_status='all', filter_shipper_received='all',
        )
else:
    sales, matched_ids, _stats, product_availabilities, product_on_hand, so_status_dict = \
        service._calculate_po_and_stock_status(
            sales, '', '', 'all', FILTER_DELIVERY_STATUS, 'all', 'all',
            show_completed=False, filter_need_transfer=False, filter_new_orders=False,
            filter_done_date_from='', filter_done_date_to='',
            filter_print_status='all', filter_shipper_received='all',
        )
    page_sales = env['sale.order'].browse(matched_ids[OFFSET:OFFSET + LIMIT])

print(f"  page_sales={len(page_sales)}, usable={bool(snapshot_match)} — sẵn sàng profile [4c]+[7]")

# ─────────────────────────────────────────────
# PROFILE ĐÚNG 2 BƯỚC NGHI VẤN — lần gọi ĐẦU TIÊN trong process này
# ─────────────────────────────────────────────
section("cProfile [4c] _fetch_packages_for_sales (LẦN GỌI ĐẦU TIÊN trong process này)")
profiler = cProfile.Profile()
profiler.enable()
so_packages_dict = service._fetch_packages_for_sales(page_sales)
profiler.disable()
buf = io.StringIO()
pstats.Stats(profiler, stream=buf).sort_stats('cumulative').print_stats(25)
print(buf.getvalue())

section("cProfile [7] _batch_transfer_suggestions (LẦN GỌI ĐẦU TIÊN trong process này)")
profiler2 = cProfile.Profile()
profiler2.enable()
transfer_map = service._batch_transfer_suggestions(page_sales, product_availabilities)
profiler2.disable()
buf2 = io.StringIO()
pstats.Stats(profiler2, stream=buf2).sort_stats('cumulative').print_stats(25)
print(buf2.getvalue())

section("XONG — gửi lại 2 bảng cProfile trên để tìm đúng hàm nào đang được 'nạp lần đầu'")
