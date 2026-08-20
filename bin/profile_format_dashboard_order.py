# -*- coding: utf-8 -*-
"""
profile_format_dashboard_order.py
====================================
bin/profile_dashboard_data_steps.py đã khoanh vùng: _format_dashboard_order() (vòng lặp cho
372 đơn) chiếm 4.57s/6.59s tổng — đây là bước tốn nhất. Script này dùng cProfile để biết
CHÍNH XÁC hàm/dòng nào bên trong _format_dashboard_order ngốn thời gian nhất (nghi ngờ: tính
thuế line.tax_id.compute_all() gọi riêng từng dòng sản phẩm, hoặc N+1 query khi truy cập
picking_type_id/x_pack_packer_user_id/shipper_user_id/product_id cho từng picking/line).

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/profile_format_dashboard_order.py
"""

import cProfile
import pstats
import io

service = env['hlv.delivery.planner.service'].sudo()

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

WAREHOUSE_ID = '3'
FILTER_DELIVERY_STATUS = 'pending_partial'
LIMIT = 372
OFFSET = 0

section(f"Chuẩn bị input giống hệt get_dashboard_data (kho={WAREHOUSE_ID})")

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

po_by_origin = service._fetch_pos_for_sales(page_sales)
att_by_picking = service._fetch_attachments_for_pickings(page_sales.mapped('picking_ids').ids)
so_packages_dict = service._fetch_packages_for_sales(page_sales)

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

page_blocking_by_so = service._batch_blocking_moves(page_sales)
transfer_map = service._batch_transfer_suggestions(page_sales, product_availabilities)

print(f"  page_sales={len(page_sales)} sẵn sàng profile.")

section("cProfile _format_dashboard_order x{} lần".format(len(page_sales)))

profiler = cProfile.Profile()
profiler.enable()
result = [
    service._format_dashboard_order(
        so, po_by_origin, product_availabilities, product_on_hand,
        att_by_picking, so_packages_dict, so_status_dict.get(so.id, {}),
        transfer_suggestions=transfer_map.get(so.id, []),
        page_kit_tmpl_ids=page_kit_tmpl_ids,
        page_kit_bom_map=page_kit_bom_map,
        page_blocking_by_so=page_blocking_by_so,
    )
    for so in page_sales
]
profiler.disable()

buf = io.StringIO()
stats = pstats.Stats(profiler, stream=buf).sort_stats('cumulative')
stats.print_stats(30)
print(buf.getvalue())

section("Top theo tottime (thời gian THUẦN trong chính hàm đó, không tính hàm con)")
buf2 = io.StringIO()
stats2 = pstats.Stats(profiler, stream=buf2).sort_stats('tottime')
stats2.print_stats(20)
print(buf2.getvalue())
