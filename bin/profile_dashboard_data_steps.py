# -*- coding: utf-8 -*-
"""
profile_dashboard_data_steps.py
=================================
get_dashboard_data() cho kho=3/pending_partial/limit=372 đo full (bin/profile_exact_request.py)
mất 7.5-17.5s dù _calculate_po_and_stock_status riêng lẻ trước đây đo <1s cho 589 đơn (kho khác) —
nghi ngờ chi phí thật nằm ở các bước SAU khi tính stock/packing status: fetch PO/attachment/
package, batch BOM kit, batch blocking moves, batch transfer suggestions, và vòng lặp
_format_dashboard_order cho từng đơn. Script này chạy lại CHÍNH bộ tham số đó nhưng đo riêng
từng bước để biết bước nào chiếm phần lớn thời gian.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/profile_dashboard_data_steps.py
"""

import time

service = env['hlv.delivery.planner.service'].sudo()

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

WAREHOUSE_ID = '3'
FILTER_DELIVERY_STATUS = 'pending_partial'
LIMIT = 372
OFFSET = 0

section(f"get_dashboard_data từng bước — kho={WAREHOUSE_ID}, {FILTER_DELIVERY_STATUS}, limit={LIMIT}")

t_start = time.time()

# --- Bước 1: search domain + search ---
t0 = time.time()
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
t1 = time.time()
print(f"  [1] search_domain + search           : {t1 - t0:.3f}s | matched={len(sales)}")

# --- Bước 2: snapshot fast-path check ---
t0 = time.time()
can_use = service._can_use_snapshot_dashboard_match(
    filter_po_date_from='', filter_po_date_to='', filter_po_status='all',
    filter_done_date_from='', filter_done_date_to='', filter_need_transfer=False, domain=None,
)
snapshot_match = None
if can_use:
    snapshot_match = service._get_snapshot_dashboard_match(
        sales, filter_delivery_status=FILTER_DELIVERY_STATUS, filter_stock_status='all',
        filter_packing_status='all', show_completed=False, filter_new_orders=False,
        filter_print_status='all', filter_shipper_received='all',
    )
t1 = time.time()
print(f"  [2] snapshot fast-path check          : {t1 - t0:.3f}s | usable={bool(snapshot_match)}")

# --- Bước 3: stock/packing status (fast path hoặc fallback đầy đủ) ---
t0 = time.time()
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
t1 = time.time()
print(f"  [3] _calculate_po_and_stock_status    : {t1 - t0:.3f}s | page_sales={len(page_sales)} matched_total={len(matched_ids)}")

# --- Bước 4: fetch PO / attachment / package ---
t0 = time.time()
po_by_origin = service._fetch_pos_for_sales(page_sales)
t1 = time.time()
print(f"  [4a] _fetch_pos_for_sales             : {t1 - t0:.3f}s")

t0 = time.time()
att_by_picking = service._fetch_attachments_for_pickings(page_sales.mapped('picking_ids').ids)
t1 = time.time()
print(f"  [4b] _fetch_attachments_for_pickings   : {t1 - t0:.3f}s")

t0 = time.time()
so_packages_dict = service._fetch_packages_for_sales(page_sales)
t1 = time.time()
print(f"  [4c] _fetch_packages_for_sales         : {t1 - t0:.3f}s")

# --- Bước 5: BOM kit batch load ---
t0 = time.time()
page_tmpl_ids = page_sales.mapped('order_line.product_id.product_tmpl_id').ids
page_kits = env['mrp.bom'].sudo().search([
    ('product_tmpl_id', 'in', page_tmpl_ids), ('type', '=', 'phantom'),
]) if page_tmpl_ids else env['mrp.bom']
page_kit_tmpl_ids = set(page_kits.mapped('product_tmpl_id').ids)
page_kit_bom_map = {'by_product': {}, 'by_template': {}}
for bom in page_kits:
    if bom.product_id:
        page_kit_bom_map['by_product'][bom.product_id.id] = bom
    else:
        page_kit_bom_map['by_template'].setdefault(bom.product_tmpl_id.id, bom)
t1 = time.time()
print(f"  [5] BOM kit batch load                : {t1 - t0:.3f}s | kits={len(page_kits)}")

# --- Bước 6: blocking moves batch ---
t0 = time.time()
page_blocking_by_so = service._batch_blocking_moves(page_sales)
t1 = time.time()
print(f"  [6] _batch_blocking_moves              : {t1 - t0:.3f}s")

# --- Bước 7: transfer suggestions batch ---
t0 = time.time()
transfer_map = service._batch_transfer_suggestions(page_sales, product_availabilities)
t1 = time.time()
print(f"  [7] _batch_transfer_suggestions        : {t1 - t0:.3f}s")

# --- Bước 7b: kit component free stock batch (fix mới — trước đây _format_dashboard_order
# tự tính lại cái này MỖI đơn, xem bin/profile_format_dashboard_order.py) ---
t0 = time.time()
page_kit_comp_free = service._batch_kit_component_free_stock(page_sales, page_kit_bom_map)
t1 = time.time()
print(f"  [7b] _batch_kit_component_free_stock    : {t1 - t0:.3f}s")

# --- Bước 8: format_dashboard_order loop (từng đơn) ---
t0 = time.time()
result = [
    service._format_dashboard_order(
        so, po_by_origin, product_availabilities, product_on_hand,
        att_by_picking, so_packages_dict, so_status_dict.get(so.id, {}),
        transfer_suggestions=transfer_map.get(so.id, []),
        page_kit_tmpl_ids=page_kit_tmpl_ids,
        page_kit_bom_map=page_kit_bom_map,
        page_blocking_by_so=page_blocking_by_so,
        page_kit_comp_free=page_kit_comp_free,
    )
    for so in page_sales
]
t1 = time.time()
print(f"  [8] _format_dashboard_order x{len(page_sales)} loop : {t1 - t0:.3f}s ({(t1 - t0) / max(len(page_sales), 1) * 1000:.2f}ms/đơn)")

# --- Bước 9: warehouses/tags read ---
t0 = time.time()
warehouses = env['stock.warehouse'].search_read([], ['id', 'name'])
tags = env['crm.tag'].search_read([], ['id', 'name'])
t1 = time.time()
print(f"  [9] warehouses/tags search_read        : {t1 - t0:.3f}s")

t_end = time.time()
section(f"TỔNG: {t_end - t_start:.3f}s")
print("  So sánh với bin/profile_exact_request.py để xem tổng có khớp không, và bước nào")
print("  chiếm phần lớn — đó là nơi cần tối ưu tiếp theo.")
