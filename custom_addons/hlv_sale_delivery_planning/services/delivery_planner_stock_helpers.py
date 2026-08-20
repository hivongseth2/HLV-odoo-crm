from odoo import models, api


class DeliveryPlannerServiceStockHelpers(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    @api.model
    def _batch_blocking_moves(self, page_sales):
        """
        Batch load internal moves đang block hàng tại kho của từng SO trên trang.
        Thay 12× stock.move.search per-SO bằng 1 batch query.
        Trả về: {so_id: {product_id: [{picking_id, picking_name, ...}]}}
        """
        if not page_sales:
            return {}
        so_wh_locs = {}
        all_pending_pids = set()
        for so in page_sales:
            wh_root = so.warehouse_id.view_location_id or so.warehouse_id.lot_stock_id if so.warehouse_id else False
            if not so.warehouse_id or not wh_root:
                continue
            so_wh_locs[so.id] = (so.warehouse_id.id, wh_root.id)
            for line in so.order_line:
                if line.display_type or not line.product_id:
                    continue
                if line.product_id.type == 'service':
                    continue
                if (line.product_uom_qty - line.qty_delivered) > 0:
                    all_pending_pids.add(line.product_id.id)

        if not all_pending_pids or not so_wh_locs:
            return {}

        all_root_locs = list({v[1] for v in so_wh_locs.values()})
        child_locs = self.env['stock.location'].sudo().search([
            ('id', 'child_of', all_root_locs), ('usage', '=', 'internal'),
        ])
        loc_to_whs = {}
        for so_id, (wh_id, root_loc) in so_wh_locs.items():
            for loc in child_locs:
                if loc.parent_path and f'/{root_loc}/' in loc.parent_path:
                    loc_to_whs.setdefault(loc.id, set()).add(wh_id)

        if not loc_to_whs:
            return {}

        # SQL thẳng thay vì search_read([...], ['product_id', ...]) — search_read() trả
        # Many2one dạng [id, display_name], buộc tính display_name cho product.product (bị
        # module renting override nặng) dù ở đây chỉ cần ID. Xem giải thích đầy đủ ở
        # delivery_planner_stock.py._calculate_po_and_stock_status (cùng bug, đã đo qua
        # bin/profile_cold_start_full.py).
        self.env.cr.execute("""
            SELECT sm.product_id, sm.location_id, sm.quantity, sm.picking_id
              FROM stock_move sm
              JOIN stock_picking sp ON sp.id = sm.picking_id
             WHERE sm.product_id = ANY(%s)
               AND sm.state IN ('assigned', 'partially_available', 'confirmed', 'waiting')
               AND sm.location_id = ANY(%s)
               AND sm.sale_line_id IS NULL
               AND sp.state NOT IN ('done', 'cancel')
        """, (list(all_pending_pids), list(loc_to_whs.keys())))
        raw_moves = [
            {
                'product_id': [r[0]] if r[0] else False,
                'location_id': [r[1]] if r[1] else False,
                'quantity': r[2],
                'picking_id': [r[3]] if r[3] else False,
            }
            for r in self.env.cr.fetchall()
        ]

        pk_ids = list({mv['picking_id'][0] for mv in raw_moves if mv.get('picking_id')})
        pk_info = {}
        if pk_ids:
            for r in self.env['stock.picking'].sudo().search_read(
                [('id', 'in', pk_ids)],
                ['id', 'name', 'state', 'origin', 'picking_type_id'],
            ):
                pt_id = r['picking_type_id'][0] if r.get('picking_type_id') else None
                pk_info[r['id']] = {
                    'name': r['name'], 'state': r['state'],
                    'origin': r.get('origin') or '', 'pt_id': pt_id,
                }
            pt_ids = list({v['pt_id'] for v in pk_info.values() if v['pt_id']})
            if pt_ids:
                pt_map = {r['id']: r for r in self.env['stock.picking.type'].sudo().search_read(
                    [('id', 'in', pt_ids)], ['id', 'name', 'code'],
                )}
                for info in pk_info.values():
                    pt = pt_map.get(info['pt_id'], {})
                    info['type_name'] = pt.get('name') or ''
                    info['type_code'] = pt.get('code') or ''

        wh_to_sos = {}
        for so_id, (wh_id, _) in so_wh_locs.items():
            wh_to_sos.setdefault(wh_id, []).append(so_id)

        result = {}
        for mv in raw_moves:
            pid = mv['product_id'][0]
            qty = mv.get('quantity') or 0
            if qty <= 0:
                continue
            loc_id = mv['location_id'][0] if mv.get('location_id') else None
            pk_id = mv['picking_id'][0] if mv.get('picking_id') else None
            if not loc_id or not pk_id:
                continue
            pk_data = pk_info.get(pk_id, {})
            for wh_id in loc_to_whs.get(loc_id, set()):
                for so_id in wh_to_sos.get(wh_id, []):
                    entries = result.setdefault(so_id, {}).setdefault(pid, {})
                    if pk_id in entries:
                        entries[pk_id]['qty'] += qty
                    else:
                        entries[pk_id] = {
                            'picking_id': pk_id,
                            'picking_name': pk_data.get('name', ''),
                            'picking_type': pk_data.get('type_name', ''),
                            'picking_code': pk_data.get('type_code', ''),
                            'origin': pk_data.get('origin', ''),
                            'state': pk_data.get('state', ''),
                            'qty': qty,
                        }
        return {
            so_id: {pid: list(entries.values()) for pid, entries in by_prod.items()}
            for so_id, by_prod in result.items()
        }

    @api.model
    def _batch_kit_component_free_stock(self, page_sales, kit_bom_map):
        """
        Batch tính tồn khả dụng (quantity - reserved_quantity) cho TẤT CẢ sản phẩm component
        của Kit (phantom BOM) trên toàn trang, theo từng kho — MỘT LẦN duy nhất.

        Trước đây _format_dashboard_order tự tính lại cái này (1 location search + 1 quant
        read_group) cho MỖI đơn riêng lẻ — nếu N đơn cùng kho thì lặp lại N lần một kết quả
        giống hệt nhau. Đo thực tế: 372 đơn cùng kho -> read_group gọi 372 lần, chiếm ~3.2s/6.2s
        tổng thời gian format trang (xem bin/profile_format_dashboard_order.py).

        Trả về: {(component_product_id, warehouse_id): free_qty}
        """
        if not page_sales or not kit_bom_map:
            return {}

        seen_bom_ids = set()
        all_comp_prod_ids = set()
        for bom in (
            list(kit_bom_map.get('by_product', {}).values())
            + list(kit_bom_map.get('by_template', {}).values())
        ):
            if not bom or bom.id in seen_bom_ids:
                continue
            seen_bom_ids.add(bom.id)
            for comp in bom.bom_line_ids:
                if comp.product_id:
                    all_comp_prod_ids.add(comp.product_id.id)

        if not all_comp_prod_ids:
            return {}

        wh_ids = {so.warehouse_id.id for so in page_sales if so.warehouse_id}
        if not wh_ids:
            return {}

        loc_to_wh_id = self._get_loc_to_wh_map(frozenset(wh_ids))
        if not loc_to_wh_id:
            return {}

        kit_comp_free = {}
        for row in self.env['stock.quant'].sudo().read_group(
            domain=[
                ('product_id', 'in', list(all_comp_prod_ids)),
                ('location_id', 'in', list(loc_to_wh_id.keys())),
            ],
            fields=['quantity:sum', 'reserved_quantity:sum'],
            groupby=['product_id', 'location_id'],
            lazy=False,
        ):
            pid_raw = row.get('product_id')
            loc_raw = row.get('location_id')
            if not pid_raw or not loc_raw:
                continue
            pid = pid_raw[0] if isinstance(pid_raw, (list, tuple)) else pid_raw
            loc_id = loc_raw[0] if isinstance(loc_raw, (list, tuple)) else loc_raw
            wh_id = loc_to_wh_id.get(loc_id)
            if wh_id:
                free = max((row.get('quantity') or 0.0) - (row.get('reserved_quantity') or 0.0), 0.0)
                key = (pid, wh_id)
                kit_comp_free[key] = kit_comp_free.get(key, 0.0) + free
        return kit_comp_free

    @api.model
    def _batch_transfer_suggestions(self, page_sales, product_availabilities):
        """
        Batch version: tính transfer_suggestions cho toàn trang trong 1-2 queries
        thay vì N × M × P queries khi tính riêng từng SO.
        Trả về: {so_id: [{product_id, product_name, shortage, to_warehouse_name, sources}]}
        """
        if not page_sales:
            return {}

        # Làm nóng prefetch picking_ids -> move_ids -> sale_line_id/product_id cho TOÀN TRANG
        # một lần — nếu không, vòng lặp per-SO dưới đây (so.picking_ids, pk.move_ids) sẽ fetch
        # riêng lẻ từng đơn (đo thực tế: ~700 query dư cho 373 đơn khi env chưa từng truy cập
        # các field này, xem bin/profile_cold_start.py — đây LUÔN xảy ra trên request HTTP thật
        # vì mỗi request là 1 env/cache mới, không như test lặp lại trong cùng 1 shell).
        page_moves = page_sales.mapped('picking_ids').mapped('move_ids')
        page_moves.mapped('sale_line_id')
        page_moves.mapped('product_id')

        # Bước 1: Xác định shortage per SO từ product_availabilities đã có
        all_tmpl_ids = page_sales.mapped('order_line.product_id.product_tmpl_id').ids
        kits = self.env['mrp.bom'].sudo().search([
            ('product_tmpl_id', 'in', all_tmpl_ids), ('type', '=', 'phantom'),
        ]) if all_tmpl_ids else self.env['mrp.bom']
        kit_tmpl_ids = set(kits.mapped('product_tmpl_id').ids)

        so_shortages = {}    # {so_id: [{pid, pname, shortage}]}
        dest_wh_by_so = {}   # {so_id: warehouse_id}
        shortage_prod_ids = set()

        for so in page_sales:
            if not so.warehouse_id:
                continue
            dest_wh_id = so.warehouse_id.id
            dest_wh_by_so[so.id] = dest_wh_id

            active_pks = so.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel') and not p.return_id
            )
            products_with_demand = {
                mv.product_id.id
                for pk in active_pks
                for mv in pk.move_ids
                if mv.state not in ('cancel', 'done')
            }
            line_reserved = {}
            for mv in active_pks.mapped('move_ids').filtered(
                lambda m: m.state not in ('cancel', 'done')
            ):
                lid = mv.sale_line_id.id
                if lid:
                    line_reserved[lid] = line_reserved.get(lid, 0.0) + mv.quantity

            shortages = []
            for line in so.order_line:
                if line.display_type or not line.product_id:
                    continue
                if line.product_id.type == 'service':
                    continue
                if line.product_id.product_tmpl_id.id in kit_tmpl_ids:
                    continue
                pid = line.product_id.id
                if pid not in products_with_demand:
                    continue
                pending = line.product_uom_qty - line.qty_delivered
                if pending <= 0:
                    continue
                avail = (product_availabilities.get((pid, dest_wh_id), 0.0)
                         + line_reserved.get(line.id, 0.0))
                if pending - avail > 0:
                    shortages.append({
                        'product_id': pid,
                        'product_name': line.product_id.display_name,
                        'shortage': pending - avail,
                    })
                    shortage_prod_ids.add(pid)
            if shortages:
                so_shortages[so.id] = shortages

        if not so_shortages:
            return {}

        # Bước 2: Kho khác (ngoài các kho đích của trang)
        all_dest_wh_ids = set(dest_wh_by_so.values())
        other_whs = self.env['stock.warehouse'].search([('id', 'not in', list(all_dest_wh_ids))])
        if not other_whs:
            return {}

        # Bước 3: Load availability tại other warehouses
        # Nếu product_availabilities đã có (vì filter_need_transfer=True), dùng trực tiếp
        other_avail = {}
        missing_keys = set()
        for pid in shortage_prod_ids:
            for wh in other_whs:
                key = (pid, wh.id)
                if key in product_availabilities:
                    other_avail[key] = product_availabilities[key]
                else:
                    missing_keys.add(key)

        if missing_keys:
            needed_wh_ids = list({k[1] for k in missing_keys})
            needed_prod_ids = list({k[0] for k in missing_keys})
            needed_whs = self.env['stock.warehouse'].browse(needed_wh_ids)
            root_loc_ids = [wh.lot_stock_id.id for wh in needed_whs if wh.lot_stock_id]

            if root_loc_ids:
                child_locs = self.env['stock.location'].sudo().search([
                    ('id', 'child_of', root_loc_ids), ('usage', '=', 'internal'),
                ])
                loc_to_owh = {}
                for wh in needed_whs:
                    if not wh.lot_stock_id:
                        continue
                    for loc in child_locs:
                        if loc.parent_path and f'/{wh.lot_stock_id.id}/' in loc.parent_path:
                            if loc.id not in loc_to_owh:
                                loc_to_owh[loc.id] = wh.id

                if loc_to_owh:
                    # ONE quant query
                    q_rows = self.env['stock.quant'].sudo().read_group(
                        domain=[
                            ('product_id', 'in', needed_prod_ids),
                            ('location_id', 'in', list(loc_to_owh.keys())),
                        ],
                        fields=['quantity:sum', 'reserved_quantity:sum'],
                        groupby=['product_id', 'location_id'],
                    )
                    for row in q_rows:
                        pid_raw = row.get('product_id')
                        loc_raw = row.get('location_id')
                        if not pid_raw or not loc_raw:
                            continue
                        pid = pid_raw[0] if isinstance(pid_raw, (list, tuple)) else pid_raw
                        loc_id = loc_raw[0] if isinstance(loc_raw, (list, tuple)) else loc_raw
                        wh_id = loc_to_owh.get(loc_id)
                        if wh_id:
                            free = max(
                                (row.get('quantity') or 0.0) - (row.get('reserved_quantity') or 0.0), 0.0
                            )
                            key = (pid, wh_id)
                            other_avail[key] = other_avail.get(key, 0.0) + free


        # Bước 4: Build kết quả per SO
        wh_name = {wh.id: wh.name for wh in other_whs}
        so_wh_name = {so.id: so.warehouse_id.name for so in page_sales if so.warehouse_id}
        result = {}
        for so_id, shortages in so_shortages.items():
            dest_wh = self.env['stock.warehouse'].browse(dest_wh_by_so.get(so_id))
            ordered_other_whs = self._order_source_warehouses(dest_wh, other_whs)
            suggestions = []
            for sp in shortages:
                pid, remaining = sp['product_id'], sp['shortage']
                sources = []
                for wh in ordered_other_whs:
                    if remaining <= 0:
                        break
                    available = other_avail.get((pid, wh.id), 0.0)
                    if available > 0:
                        suggest_qty = min(available, remaining)
                        sources.append({
                            'from_warehouse_id': wh.id,
                            'from_warehouse_name': wh_name.get(wh.id, ''),
                            'available_qty': available,
                            'suggested_qty': suggest_qty,
                            'blocking_pickings': [],
                        })
                        remaining -= suggest_qty
                if sources:
                    suggestions.append({
                        'product_id': pid,
                        'product_name': sp['product_name'],
                        'shortage': sp['shortage'],
                        'to_warehouse_name': so_wh_name.get(so_id, ''),
                        'sources': sources,
                    })
            if suggestions:
                result[so_id] = suggestions
        return result
