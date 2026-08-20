# -*- coding: utf-8 -*-
"""
profile_query_count_steps.py
==============================
_fetch_packages_for_sales / _batch_transfer_suggestions cho ra lúc 5-6 query, lúc 700+ query
(cùng code, cùng kwargs, staging không ai thao tác) — nghi ngờ do cache field bị invalidate
giữa các lần chạy (VD do cron mới chạy mỗi phút + hook dirty-theo-sản-phẩm ghi thường xuyên,
kích hoạt tín hiệu invalidate cache xuyên tiến trình của Odoo), KHÔNG phải do data thật đổi.

Script này chạy 2 LẦN LIÊN TIẾP, sát nhau (không có khoảng trễ, không phải mở lại shell) để
phân biệt: nếu 2 lần vẫn RA SỐ KHÁC NHAU dù chạy sát nhau trong cùng 1 process/transaction,
gần như chắc chắn là cache-invalidation-churn, không phải do data thay đổi theo thời gian.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/profile_query_count_steps.py
"""

import time

service = env['hlv.delivery.planner.service'].sudo()
cr = env.cr

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

def qc():
    return cr.sql_log_count

WAREHOUSE_ID = '3'
FILTER_DELIVERY_STATUS = 'pending_partial'
LIMIT = 373
OFFSET = 0


def run_once(run_label):
    section(f"{run_label} — kho={WAREHOUSE_ID}, {FILTER_DELIVERY_STATUS}, limit={LIMIT}")

    q0 = qc()
    t_start = time.time()

    def report(label, q_before, t_before, extra=''):
        q_after = qc()
        t_after = time.time()
        print(f"  {label:42s}: {t_after - t_before:6.3f}s | +{q_after - q_before:5d} queries" + (f" | {extra}" if extra else ""))
        return q_after, t_after

    q, t = qc(), time.time()
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
    q, t = report("[1] search_domain + search", q, t, f"matched={len(sales)}")

    can_use = service._can_use_snapshot_dashboard_match(
        filter_po_date_from='', filter_po_date_to='', filter_po_status='all',
        filter_done_date_from='', filter_done_date_to='', filter_need_transfer=False, domain=None,
    )
    snapshot_match = service._get_snapshot_dashboard_match(
        sales, filter_delivery_status=FILTER_DELIVERY_STATUS, filter_stock_status='all',
        filter_packing_status='all', show_completed=False, filter_new_orders=False,
        filter_print_status='all', filter_shipper_received='all',
    ) if can_use else None
    q, t = report("[2] snapshot fast-path check", q, t, f"usable={bool(snapshot_match)}")

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
    q, t = report("[3] _calculate_po_and_stock_status", q, t, f"page_sales={len(page_sales)}")

    po_by_origin = service._fetch_pos_for_sales(page_sales)
    q, t = report("[4a] _fetch_pos_for_sales", q, t)

    att_by_picking = service._fetch_attachments_for_pickings(page_sales.mapped('picking_ids').ids)
    q, t = report("[4b] _fetch_attachments_for_pickings", q, t)

    so_packages_dict = service._fetch_packages_for_sales(page_sales)
    q, t = report("[4c] _fetch_packages_for_sales", q, t)

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
    q, t = report("[5] BOM kit batch load", q, t, f"kits={len(page_kits)}")

    page_blocking_by_so = service._batch_blocking_moves(page_sales)
    q, t = report("[6] _batch_blocking_moves", q, t)

    transfer_map = service._batch_transfer_suggestions(page_sales, product_availabilities)
    q, t = report("[7] _batch_transfer_suggestions", q, t)

    page_kit_comp_free = service._batch_kit_component_free_stock(page_sales, page_kit_bom_map)
    q, t = report("[7b] _batch_kit_component_free_stock", q, t)

    result = []
    CHUNK = 50
    so_list = list(page_sales)
    for start in range(0, len(so_list), CHUNK):
        chunk = so_list[start:start + CHUNK]
        qc0, tc0 = qc(), time.time()
        for so in chunk:
            result.append(service._format_dashboard_order(
                so, po_by_origin, product_availabilities, product_on_hand,
                att_by_picking, so_packages_dict, so_status_dict.get(so.id, {}),
                transfer_suggestions=transfer_map.get(so.id, []),
                page_kit_tmpl_ids=page_kit_tmpl_ids,
                page_kit_bom_map=page_kit_bom_map,
                page_blocking_by_so=page_blocking_by_so,
                page_kit_comp_free=page_kit_comp_free,
            ))
        qc1, tc1 = qc(), time.time()
        n = len(chunk)
        print(f"  [8] đơn {start:4d}-{start + n - 1:4d}: {tc1 - tc0:6.3f}s | +{qc1 - qc0:5d} queries "
              f"({(qc1 - qc0) / n:.2f} query/đơn)")

    t_end = time.time()
    q_end = qc()
    print(f"\n  >>> {run_label} TỔNG: {t_end - t_start:.3f}s | {q_end - q0} queries <<<")
    return q_end - q0, t_end - t_start


r1 = run_once("LẦN 1 (ngay bây giờ)")
r2 = run_once("LẦN 2 (chạy NGAY SAU, cùng process/transaction, không nghỉ)")

section("SO SÁNH")
print(f"  Lần 1: {r1[1]:.3f}s | {r1[0]} queries")
print(f"  Lần 2: {r2[1]:.3f}s | {r2[0]} queries")
if abs(r1[0] - r2[0]) > 50:
    print("  => Query count KHÁC NHAU đáng kể dù chạy sát nhau, cùng transaction —")
    print("     rất có thể do cache field bị invalidate giữa 2 lần (cron/hook ghi liên tục),")
    print("     KHÔNG phải do data thật đổi theo thời gian.")
else:
    print("  => Query count ổn định giữa 2 lần chạy sát nhau — nếu lần trước ra số khác hẳn,")
    print("     nhiều khả năng do DATA THẬT đã đổi theo thời gian (cron/tự động khác ghi),")
    print("     không phải do cache-invalidation-churn.")
