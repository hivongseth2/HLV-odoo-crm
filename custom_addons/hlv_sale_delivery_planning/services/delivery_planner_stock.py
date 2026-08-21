from odoo import models, tools
import pytz
from odoo.fields import Date as OdooDate


class DeliveryPlannerServiceStock(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    @tools.ormcache('wh_ids')
    def _get_loc_to_wh_map(self, wh_ids):
        """Quy đổi location nội bộ -> kho cha (dùng để gộp tồn quant theo kho). Cấu trúc
        kho/location gần như không đổi (chỉ admin cấu hình lại mới đổi), nhưng trước đây bị
        tính lại bằng vòng lặp lồng nhau (số location x số kho) MỖI REQUEST — cache theo tập
        kho cần dùng để khỏi lặp lại. Cache tự hết khi worker restart; nếu admin đổi cấu trúc
        kho/location lúc server đang chạy, cần restart hoặc gọi
        _get_loc_to_wh_map.clear_cache(env['hlv.delivery.planner.service']) để thấy ngay."""
        all_wh_objs = self.env['stock.warehouse'].browse(list(wh_ids))
        root_loc_ids = [
            (wh.view_location_id or wh.lot_stock_id).id
            for wh in all_wh_objs
            if wh.view_location_id or wh.lot_stock_id
        ]
        all_child_locs = self.env['stock.location'].sudo().search([
            ('id', 'child_of', root_loc_ids), ('usage', '=', 'internal'),
        ]) if root_loc_ids else self.env['stock.location']
        loc_to_wh_id = {}
        for loc in all_child_locs:
            if not loc.parent_path:
                continue
            best_wh_id, best_pos = None, -1
            for wh in all_wh_objs:
                wh_root = wh.view_location_id or wh.lot_stock_id
                if not wh_root:
                    continue
                pos = loc.parent_path.find(f'/{wh_root.id}/')
                if pos > best_pos:
                    best_pos, best_wh_id = pos, wh.id
            if best_wh_id is not None:
                loc_to_wh_id[loc.id] = best_wh_id
        return loc_to_wh_id

    def _calculate_po_and_stock_status(
        self, sales, po_date_from, po_date_to, po_status,
        filter_delivery_status, filter_stock_status, filter_packing_status,
        show_completed=False, filter_need_transfer=False,
        filter_new_orders=False,
        filter_done_date_from='', filter_done_date_to='',
        filter_print_status='all', filter_shipper_received='all',
    ):
        """
        Phase 3 optimization: thay thế ORM loop per-SO bằng ~11 batch SQL queries cố định.
        Không còn N×M queries hay for-loop với ORM access per SO.
        """
        # --- 1. Lọc theo tiêu chí PO (nếu có) ---
        if po_date_from or po_date_to or (po_status and po_status != 'all'):
            po_domain = [('origin', 'in', sales.mapped('name'))]
            if po_date_from:
                po_domain.append(('date_planned', '>=', po_date_from))
            if po_date_to:
                po_domain.append(('date_planned', '<=', po_date_to + ' 23:59:59'))
            matching_pos = self.env['purchase.order'].search(po_domain)
            if po_status and po_status != 'all':
                matching_pos = matching_pos.filtered(
                    lambda po: self._delivery_planner_po_receipt_status(po) == po_status
                )
            origins = list({po.origin for po in matching_pos if po.origin})
            sales = sales.filtered(lambda s: s.name in origins)

        # --- 1b. Lọc theo ngày hoàn thành (date_done của phiếu OUT) ---
        if filter_done_date_from or filter_done_date_to:
            from datetime import datetime
            _tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'Asia/Ho_Chi_Minh')
            pk_dom = [('picking_type_code', '=', 'outgoing'), ('state', '=', 'done'), ('sale_id', 'in', sales.ids)]
            if filter_done_date_from:
                utc_from = _tz.localize(datetime.strptime(filter_done_date_from, '%Y-%m-%d')).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
                pk_dom.append(('date_done', '>=', utc_from))
            if filter_done_date_to:
                utc_to = _tz.localize(datetime.strptime(filter_done_date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
                pk_dom.append(('date_done', '<=', utc_to))
            done_so_ids = set(self.env['stock.picking'].search(pk_dom).mapped('sale_id').ids)
            sales = sales.filtered(lambda s: s.id in done_so_ids)

        _empty = {'total': 0, 'ready': 0, 'partial': 0, 'out_of_stock': 0,
                  'packing_fully': 0, 'packing_partial': 0, 'packing_unpacked': 0, 'packing_waiting': 0}
        if not sales:
            return sales, [], _empty, {}, {},{}

        so_ids = sales.ids
        today_date = OdooDate.context_today(self)
        user_tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'Asia/Ho_Chi_Minh')

        # ====== PHASE 1: Batch load TẤT CẢ data cần thiết ======

        # [A] SO metadata — 1 query
        so_mf = set(self.env['sale.order']._fields.keys())
        so_rf = ['id', 'warehouse_id'] + [f for f in [
            'x_picking_slip_printed', 'x_studio_misa_order_date', 'date_order', 'x_plan_unread_message',
        ] if f in so_mf]
        so_data = {r['id']: r for r in sales.read(so_rf)}

        # [B] Order lines (product lines only, bỏ section/note) — 1 query
        line_recs = self.env['sale.order.line'].search_read(
            [('order_id', 'in', so_ids), ('display_type', '=', False)],
            ['id', 'order_id', 'product_id', 'product_uom_qty', 'qty_delivered'],
        )
        all_line_ids = [r['id'] for r in line_recs]
        line_to_so = {r['id']: r['order_id'][0] for r in line_recs}
        lines_by_so = {}
        for r in line_recs:
            lines_by_so.setdefault(r['order_id'][0], []).append(r)

        # [C] Product type + tmpl_id — 1 query
        all_pid_set = {r['product_id'][0] for r in line_recs if r.get('product_id')}
        product_map = {}
        if all_pid_set:
            for r in self.env['product.product'].sudo().search_read(
                [('id', 'in', list(all_pid_set))], ['id', 'type', 'product_tmpl_id'],
            ):
                product_map[r['id']] = r

        # [D] Kit BOMs — 1 query
        all_tmpl_ids = list({
            product_map[pid]['product_tmpl_id'][0]
            for pid in all_pid_set
            if pid in product_map and product_map[pid].get('product_tmpl_id')
        })
        kits = self.env['mrp.bom'].sudo().search([
            ('product_tmpl_id', 'in', all_tmpl_ids), ('type', '=', 'phantom'),
        ]) if all_tmpl_ids else self.env['mrp.bom']
        kit_tmpl_ids = set(kits.mapped('product_tmpl_id').ids)

        # [D2] Kit BOM components — 1 query
        # Xây kit_comp_map: {kit_tmpl_id: [(comp_pid, qty_per_kit), ...]}
        kit_comp_map = {}
        if kits:
            _bom_line_recs = self.env['mrp.bom.line'].sudo().search_read(
                [('bom_id', 'in', kits.ids)],
                ['bom_id', 'product_id', 'product_qty'],
            )
            _bom_id_to_tmpl = {bom.id: bom.product_tmpl_id.id for bom in kits}
            _bom_prod_qty = {bom.id: bom.product_qty or 1.0 for bom in kits}
            for _bl in _bom_line_recs:
                _bid = _bl['bom_id'][0] if isinstance(_bl['bom_id'], (list, tuple)) else _bl['bom_id']
                _cpid = _bl['product_id'][0] if isinstance(_bl['product_id'], (list, tuple)) else _bl['product_id']
                _tmpl = _bom_id_to_tmpl.get(_bid)
                if _tmpl and _cpid:
                    _qty_per_kit = (_bl.get('product_qty') or 0.0) / _bom_prod_qty.get(_bid, 1.0)
                    if _qty_per_kit > 0:
                        kit_comp_map.setdefault(_tmpl, []).append((_cpid, _qty_per_kit))

        # [D3] Done outgoing moves cho kit SOLs có qty_delivered=0
        # Trường hợp BOM explosion thành công nhưng bom_line_id=NULL →
        # Odoo MRP không tính được qty_delivered → dùng done moves trực tiếp
        kit_sol_id_set = set()
        for _r in line_recs:
            _pid_raw = _r.get('product_id')
            _pid = _pid_raw[0] if isinstance(_pid_raw, (list, tuple)) else _pid_raw
            if not _pid or (_r.get('qty_delivered') or 0) > 0:
                continue
            _tmpl_raw = product_map.get(_pid, {}).get('product_tmpl_id')
            _tmpl_id = _tmpl_raw[0] if isinstance(_tmpl_raw, (list, tuple)) else _tmpl_raw
            if _tmpl_id and _tmpl_id in kit_tmpl_ids:
                kit_sol_id_set.add(_r['id'])
        # [D3]/[E]: dùng SQL thẳng thay vì search_read([...], ['sale_line_id', 'product_id', ...])
        # — search_read() trả Many2one dạng [id, display_name], buộc Odoo phải TÍNH display_name
        # cho sale.order.line/product.product (bị module subscription/renting override rất nặng,
        # _additional_name_per_id/_get_partner_display) dù ở đây chỉ cần lấy ID. Đo thực tế: đây
        # là nguồn ~5s+ trong tổng request (xem bin/profile_cold_start_full.py). Chỉ cần ID nên
        # query trực tiếp bằng raw SQL để bỏ qua hoàn toàn phần tính display_name.
        done_moves_by_kit_sol = {}  # {sol_id: {prod_id: total_done_qty}}
        if kit_sol_id_set:
            self.env.cr.execute("""
                SELECT sm.sale_line_id, sm.product_id, sm.quantity
                  FROM stock_move sm
                  JOIN stock_picking sp ON sp.id = sm.picking_id
                  JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
                 WHERE sm.sale_line_id = ANY(%s)
                   AND sm.state = 'done'
                   AND spt.code = 'outgoing'
            """, (list(kit_sol_id_set),))
            for _sol_id, _cpid, _qty in self.env.cr.fetchall():
                _done_map = done_moves_by_kit_sol.setdefault(_sol_id, {})
                _done_map[_cpid] = _done_map.get(_cpid, 0.0) + (_qty or 0.0)

        # [E] Active moves per sale line — 1 query
        if all_line_ids:
            self.env.cr.execute("""
                SELECT id, sale_line_id, product_id, quantity, product_uom_qty, picking_id
                  FROM stock_move
                 WHERE sale_line_id = ANY(%s)
                   AND state NOT IN ('cancel', 'done')
            """, (list(all_line_ids),))
            move_recs = [
                {
                    'id': r[0], 'sale_line_id': [r[1]],
                    'product_id': [r[2]] if r[2] else False,
                    'quantity': r[3], 'product_uom_qty': r[4],
                    'picking_id': r[5],
                }
                for r in self.env.cr.fetchall()
            ]
        else:
            move_recs = []
        moves_by_line = {}
        line_reserved_qty = {}
        for mv in move_recs:
            lid = mv['sale_line_id'][0]
            moves_by_line.setdefault(lid, []).append(mv)
            line_reserved_qty[lid] = line_reserved_qty.get(lid, 0.0) + (mv['quantity'] or 0)

        # [F] Pickings (tất cả trạng thái) — 1 query
        pick_mf = set(self.env['stock.picking']._fields.keys())
        pick_opt = [f for f in ['x_printed', 'shipper_received', 'shipper_returned'] if f in pick_mf]
        pick_fields = ['id', 'sale_id', 'state', 'picking_type_code', 'date_done',
                       'return_id', 'picking_type_id'] + pick_opt
        pick_recs = self.env['stock.picking'].sudo().search_read([('sale_id', 'in', so_ids)], pick_fields)

        # [G] Picking type sequence codes — 1 query
        pt_ids = list({r['picking_type_id'][0] for r in pick_recs if r.get('picking_type_id')})
        pt_map = {r['id']: (r.get('sequence_code') or '').upper()
                  for r in self.env['stock.picking.type'].sudo().search_read(
                      [('id', 'in', pt_ids)], ['id', 'sequence_code'])} if pt_ids else {}
        for p in pick_recs:
            pt_id = p['picking_type_id'][0] if p.get('picking_type_id') else None
            p['seq_code'] = pt_map.get(pt_id, '')
        pickings_by_so = {}
        for p in pick_recs:
            sale_id = p['sale_id'][0] if p.get('sale_id') else None
            if sale_id:
                pickings_by_so.setdefault(sale_id, []).append(p)
        # seq_code ('PICK'/'PACK'/'OUT'...) của picking chứa move, dùng để phân biệt move nào
        # còn THỰC SỰ cần lấy/đóng gói (PICK/PACK) và move nào đã qua giai đoạn đó, chỉ còn
        # chờ xuất kho (OUT) — tránh đếm trùng tồn kho đã "khóa" cho lô đã đóng gói xong khi
        # tính xem phần CÒN THIẾU của cùng dòng có hàng để đóng gói tiếp hay không.
        pick_seq_by_id = {p['id']: p['seq_code'] for p in pick_recs}

        # [H] Build product_qty_cache + batch quant queries (1 location + 1 quant + 1 int_moves)
        product_qty_cache = {}
        for r in line_recs:
            pid = r['product_id'][0] if r.get('product_id') else None
            if not pid or product_map.get(pid, {}).get('type') == 'service':
                continue
            wh_raw = so_data.get(r['order_id'][0], {}).get('warehouse_id')
            wh_id = wh_raw[0] if isinstance(wh_raw, (list, tuple)) else wh_raw
            if wh_id:
                product_qty_cache.setdefault(wh_id, set()).add(pid)
        for mv in move_recs:  # Bổ sung Kit components
            pid = mv['product_id'][0] if mv.get('product_id') else None
            so_key = line_to_so.get(mv['sale_line_id'][0])
            if pid and so_key:
                wh_raw = so_data.get(so_key, {}).get('warehouse_id')
                wh_id = wh_raw[0] if isinstance(wh_raw, (list, tuple)) else wh_raw
                if wh_id:
                    product_qty_cache.setdefault(wh_id, set()).add(pid)

        all_prod_ids_needed = set()
        for prods in product_qty_cache.values():
            all_prod_ids_needed.update(prods)
        all_needed_wh_ids = set(product_qty_cache.keys())
        if filter_need_transfer and all_prod_ids_needed:
            all_needed_wh_ids |= set(self.env['stock.warehouse'].search([]).ids)

        product_availabilities = {}
        product_on_hand = {}
        loc_to_wh_id = {}
        if all_prod_ids_needed and all_needed_wh_ids:
            loc_to_wh_id = self._get_loc_to_wh_map(frozenset(all_needed_wh_ids))
            all_cloc_ids = list(loc_to_wh_id.keys())
            if all_cloc_ids:
                for row in self.env['stock.quant'].sudo().read_group(
                    domain=[('product_id', 'in', list(all_prod_ids_needed)), ('location_id', 'in', all_cloc_ids)],
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
                        qty = row.get('quantity') or 0.0
                        free = max(qty - (row.get('reserved_quantity') or 0), 0.0)
                        key = (pid, wh_id)
                        product_on_hand[key] = product_on_hand.get(key, 0.0) + max(qty, 0.0)
                        product_availabilities[key] = product_availabilities.get(key, 0.0) + free
            for wh_id, prod_ids in product_qty_cache.items():
                for pid in prod_ids:
                    if (pid, wh_id) not in product_availabilities:
                        product_availabilities[(pid, wh_id)] = 0.0
                    if (pid, wh_id) not in product_on_hand:
                        product_on_hand[(pid, wh_id)] = 0.0

        all_warehouse_ids = set(k[1] for k in product_availabilities.keys())

        # [I] Packed quantities — DEAD CODE removed (was computed but never returned/used)
        # Previously ran a heavy stock.move.line search with dotted-path joins
        # over all matched SOs (~200-600ms). Result `packed_qty_by_so` was unused.

        # ====== PHASE 2: Status computation — pure Python dict lookups, ZERO extra queries ======
        matched_sale_ids = []
        so_status_dict = {}
        so_meta_dict = {}

        for so_id in so_ids:
            so_rec = so_data.get(so_id, {})
            wh_raw = so_rec.get('warehouse_id')
            wh_id = wh_raw[0] if isinstance(wh_raw, (list, tuple)) else wh_raw
            pickings = pickings_by_so.get(so_id, [])
            lines = lines_by_so.get(so_id, [])

            active_outflow = [
                p for p in pickings
                if p['state'] not in ('done', 'cancel')
                and p['picking_type_code'] in ('outgoing', 'internal')
                and not p.get('return_id')
            ]
            has_any_outflow = any(
                p['picking_type_code'] in ('outgoing', 'internal') and not p.get('return_id')
                for p in pickings
            )
            no_active_outflow = has_any_outflow and not bool(active_outflow)
            has_delivered_today = any(
                p['state'] == 'done' and p.get('date_done')
                and p['date_done'].replace(tzinfo=pytz.utc).astimezone(user_tz).date() == today_date
                for p in pickings
                if p['picking_type_code'] == 'outgoing' and not p.get('return_id')
            )
            if (not show_completed and no_active_outflow and not has_delivered_today
                    and not filter_done_date_from and not filter_done_date_to):
                continue

            has_delivery_pending = False
            has_stock_pending = False
            has_delivered = False
            has_deliverable_line = False
            is_fully_ready = True
            total_pending, total_avail = 0, 0
            # total_avail_active_move: giống total_avail nhưng CHỈ tính phần của dòng còn
            # THỰC SỰ cần lấy/đóng gói (còn move active ở giai đoạn PICK/PACK). Dùng riêng cho
            # quyết định packing_status: 1 dòng đã lấy+đóng gói xong (chỉ còn move active ở
            # giai đoạn OUT — chờ xuất kho) vẫn được tính vào total_avail (đúng cho stock_status,
            # vì tồn kho thật sự "khả dụng"), nhưng KHÔNG được tính là "còn hàng để đóng gói"
            # nữa — nếu không, 1 dòng khác thực sự hết hàng sẽ bị che mất, làm packing_status
            # nhảy sai qua 'unpacked' thay vì 'waiting_stock'.
            total_avail_active_move = 0

            for line in lines:
                pid = line['product_id'][0] if line.get('product_id') else None
                if not pid:
                    continue
                pdata = product_map.get(pid, {})
                qty_del = line.get('qty_delivered') or 0
                qty_ord = line.get('product_uom_qty') or 0
                pending_qty = qty_ord - qty_del
                if pdata.get('type') == 'service':
                    # Service products have no incoming/outgoing picking flow,
                    # so they must not create delivery or packing demand.
                    continue
                has_deliverable_line = True
                if qty_del > 0:
                    has_delivered = True
                tmpl_raw = pdata.get('product_tmpl_id')
                p_tmpl_id = tmpl_raw[0] if isinstance(tmpl_raw, (list, tuple)) else tmpl_raw
                is_kit = bool(p_tmpl_id and p_tmpl_id in kit_tmpl_ids)
                # Kit Fallback: BOM explosion xảy ra nhưng bom_line_id=NULL →
                # Odoo không tính qty_delivered. Dùng done outgoing moves trực tiếp.
                if is_kit and qty_del == 0 and p_tmpl_id:
                    _comp_defs = kit_comp_map.get(p_tmpl_id, [])
                    _done_by_prod = done_moves_by_kit_sol.get(line['id'], {})
                    if _comp_defs and _done_by_prod:
                        _kits_ratio = float('inf')
                        for _cpid, _qty_per_kit in _comp_defs:
                            _kits_ratio = min(_kits_ratio, _done_by_prod.get(_cpid, 0.0) / _qty_per_kit)
                        if _kits_ratio != float('inf') and _kits_ratio > 0:
                            qty_del = min(_kits_ratio, qty_ord)
                            is_kit = False  # Treat as non-kit: pending_qty sẽ xử lý đúng
                pending_qty = qty_ord - qty_del
                if pending_qty <= 0:
                    continue
                has_delivery_pending = True
                has_stock_pending = True
                total_pending += pending_qty
                if is_kit:
                    cmp_moves = moves_by_line.get(line['id'], [])
                    if not cmp_moves:
                        is_fully_ready = False
                    else:
                        for cm in cmp_moves:
                            c_pid = cm['product_id'][0] if cm.get('product_id') else None
                            c_pending = cm.get('product_uom_qty') or 0
                            if c_pending > 0 and c_pid and wh_id:
                                c_key = (c_pid, wh_id)
                                c_avail = min(
                                    product_availabilities.get(c_key, 0.0) + (cm.get('quantity') or 0),
                                    product_on_hand.get(c_key, 0.0),
                                )
                                if c_avail > 0:
                                    c_contrib = min(c_avail, c_pending)
                                    total_avail += c_contrib
                                    if pick_seq_by_id.get(cm.get('picking_id')) in ('PICK', 'PACK'):
                                        total_avail_active_move += c_contrib
                                if c_avail < c_pending:
                                    is_fully_ready = False
                else:
                    key = (pid, wh_id) if wh_id else None
                    base_free = product_availabilities.get(key, 0.0) if key else 0.0
                    qty_avail = min(
                        base_free + line_reserved_qty.get(line['id'], 0.0),
                        product_on_hand.get(key, 0.0) if key else 0.0,
                    )
                    if qty_avail > 0:
                        total_avail += min(qty_avail, pending_qty)
                    if qty_avail < pending_qty:
                        is_fully_ready = False

                    # Packing-riêng: chỉ tính phần tồn kho có thể dùng cho phần CÒN Ở giai
                    # đoạn PICK/PACK của CHÍNH dòng này (demand + đã reserve của các move đó).
                    # Không dùng line_reserved_qty (gộp cả move OUT) — 1 dòng có backorder
                    # PICK (còn thiếu hàng) NHƯNG lô trước đã pick+pack xong đang giữ ở move
                    # OUT (chờ xuất kho) thì số lượng đó KHÔNG phải hàng có thể dùng cho phần
                    # backorder còn thiếu — nếu tính lẫn sẽ báo sai "còn hàng để đóng gói".
                    pack_moves = [
                        mv for mv in moves_by_line.get(line['id'], [])
                        if pick_seq_by_id.get(mv.get('picking_id')) in ('PICK', 'PACK')
                    ]
                    pack_pending = sum(mv.get('product_uom_qty') or 0.0 for mv in pack_moves)
                    if pack_pending > 0:
                        pack_reserved = sum(mv.get('quantity') or 0.0 for mv in pack_moves)
                        pack_avail = min(
                            base_free + pack_reserved,
                            product_on_hand.get(key, 0.0) if key else 0.0,
                        )
                        if pack_avail > 0:
                            total_avail_active_move += min(pack_avail, pack_pending)

            if has_stock_pending:
                stock_status = 'ready' if is_fully_ready else (
                    'partial_ready' if total_avail > 0 else 'out_of_stock'
                )
            else:
                stock_status = 'delivered'

            has_transfer_option = False
            if filter_need_transfer and stock_status != 'ready' and wh_id:
                products_with_demand = {
                    mv['product_id'][0]
                    for line in lines
                    for mv in moves_by_line.get(line['id'], [])
                    if mv.get('product_id')
                }
                for line in lines:
                    pid = line['product_id'][0] if line.get('product_id') else None
                    if not pid or product_map.get(pid, {}).get('type') == 'service':
                        continue
                    tmpl_raw = product_map.get(pid, {}).get('product_tmpl_id')
                    p_tmpl_id = tmpl_raw[0] if isinstance(tmpl_raw, (list, tuple)) else tmpl_raw
                    if p_tmpl_id in kit_tmpl_ids or pid not in products_with_demand:
                        continue
                    pending_qty = (line.get('product_uom_qty') or 0) - (line.get('qty_delivered') or 0)
                    if pending_qty <= 0:
                        continue
                    key = (pid, wh_id)
                    if min(
                        product_availabilities.get(key, 0.0) + line_reserved_qty.get(line['id'], 0.0),
                        product_on_hand.get(key, 0.0),
                    ) >= pending_qty:
                        continue
                    for other_wh_id in all_warehouse_ids:
                        if other_wh_id != wh_id and product_availabilities.get((pid, other_wh_id), 0.0) > 0:
                            has_transfer_option = True
                            break
                    if has_transfer_option:
                        break

            if not has_deliverable_line:
                real_delivery_status = 'full'
            elif has_delivery_pending and not has_delivered:
                real_delivery_status = 'unshipped'
            elif has_delivery_pending and has_delivered:
                real_delivery_status = 'partial'
            else:
                real_delivery_status = 'full'

            if not has_delivery_pending:
                packing_status = 'delivered'
            elif not has_stock_pending:
                # Service-only pending orders have no pick/pack flow.
                packing_status = 'unpacked'
            else:
                pack_pks = [p for p in active_outflow if p['seq_code'] == 'PACK']
                done_pack_pks = [
                    p for p in pickings
                    if p['state'] == 'done' and not p.get('return_id') and p['seq_code'] == 'PACK'
                ]
                # Nếu còn phiếu PICK đang active (backorder chưa lấy hàng),
                # thì chưa thể coi là đã đóng gói đủ — dù PACK trước đó đã done.
                # VD: PACK/03044 done + OUT/07604 done (đợt 1) nhưng PICK/05791
                # vẫn assigned (backorder đợt 2) → phải là 'unpacked', không phải 'fully_packed'.
                active_pick_pks = [p for p in active_outflow if 'PICK' in p['seq_code']]
                # Lô đã đóng gói xong đang chờ ở OUT (CHƯA giao) — dù đơn còn 1 lô KHÁC
                # (backorder) đang chờ lấy/đóng gói riêng, phần đã sẵn sàng vẫn cần được đẩy
                # đi giao ngay, không nên bị "che" thành 'waiting_stock'/'unpacked' bởi phần
                # backorder còn thiếu hàng. VD thực tế: PACK/07778 done (36/50) + OUT/12363
                # assigned (chưa giao) + PICK/11534 confirmed (backorder 14 còn thiếu hàng)
                # → phải là 'fully_packed' (FE hiển thị "Đã Gói, Chờ Nhận Giao"), không phải
                # 'waiting_stock'/'unpacked' như nếu chỉ nhìn tổng total_avail của cả đơn.
                active_out_pks = [p for p in active_outflow if p['picking_type_code'] == 'outgoing']
                if done_pack_pks and not pack_pks and active_out_pks:
                    packing_status = 'fully_packed'
                elif total_avail_active_move <= 0:
                    packing_status = 'waiting_stock'
                else:
                    packing_status = 'fully_packed' if (
                        done_pack_pks and not pack_pks and not active_pick_pks
                    ) else 'unpacked'

            has_shipper = any(
                p.get('shipper_received') and not p.get('shipper_returned')
                for p in active_outflow if p['picking_type_code'] == 'outgoing'
            )
            # Dùng per-picking x_printed trên PICK active thay SO-level x_picking_slip_printed.
            # Backorder PICK của đợt sau không kế thừa trạng thái "đã in" từ đợt trước đã giao.
            # Nếu PICK đã done và PACK đang active (hàng đã lấy xong, đang chờ đóng gói),
            # dùng x_printed của done PICK để xác định "đã in, chờ đóng gói".
            active_pick_flows = [p for p in active_outflow if 'PICK' in p['seq_code']]
            active_pack_flows = [p for p in active_outflow if p['seq_code'] == 'PACK']
            if active_pick_flows:
                # PICK chưa xong: dùng x_printed của PICK đang active
                any_active_pick_printed = any(p.get('x_printed') for p in active_pick_flows)
            elif active_pack_flows:
                # PICK đã done, PACK đang active: hàng đã lấy xong, chờ đóng gói
                # → kiểm tra done PICK gần nhất có được in không
                done_pick_pks_all = [
                    p for p in pickings
                    if p['state'] == 'done' and not p.get('return_id') and 'PICK' in p['seq_code']
                ]
                any_active_pick_printed = any(p.get('x_printed') for p in done_pick_pks_all)
            else:
                any_active_pick_printed = False
            has_assigned_pick = any(p['state'] == 'assigned' for p in active_pick_flows)

            so_status_dict[so_id] = {
                'stock_status': stock_status,
                'packing_status': packing_status,
                'real_delivery_status': real_delivery_status,
                'is_returned_or_stopped': no_active_outflow and real_delivery_status != 'full',
                'has_active_pick_printed': any_active_pick_printed,
                'has_shipper_received': has_shipper,
                'has_delivered_today': has_delivered_today,
                'has_assigned_pick': has_assigned_pick,
            }
            so_meta_dict[so_id] = {
                'stock_status': stock_status,
                'packing_status': packing_status,
                'has_pending': has_delivery_pending,
                'has_transfer_option': has_transfer_option,
                'has_unread_message': bool(so_rec.get('x_plan_unread_message', False)),
            }

            is_returned_or_stopped = no_active_outflow and real_delivery_status != 'full'
            if show_completed and is_returned_or_stopped:
                matched_sale_ids.append(so_id)
                continue

            if filter_delivery_status == 'pending_partial':
                delivery_ok = real_delivery_status in ('unshipped', 'partial')
            elif filter_delivery_status in ('unshipped', 'pending'):
                delivery_ok = real_delivery_status == 'unshipped'
            elif filter_delivery_status in ('partial', 'full'):
                delivery_ok = real_delivery_status == filter_delivery_status
            else:
                delivery_ok = True

            if filter_done_date_from or filter_done_date_to:
                done_pks = [p for p in pickings if p['state'] == 'done' and p.get('date_done')]
                if not done_pks:
                    delivery_ok = False
                else:
                    # SO match nếu BẤT KỲ phiếu OUT done nào có date_done nằm trong khoảng,
                    # không chỉ phiếu cuối cùng. (Trước đây dùng max() => sai khi SO có
                    # nhiều phiếu giao ở nhiều ngày khác nhau.)
                    any_match = False
                    for p in done_pks:
                        d_str = p['date_done'].replace(tzinfo=pytz.utc).astimezone(user_tz).strftime('%Y-%m-%d')
                        if filter_done_date_from and d_str < filter_done_date_from:
                            continue
                        if filter_done_date_to and d_str > filter_done_date_to:
                            continue
                        any_match = True
                        break
                    delivery_ok = any_match

            if has_delivered_today and (real_delivery_status == 'full' or not has_assigned_pick):
                effective_packing = 'delivered_today'
                delivery_ok = True
            elif has_shipper:
                effective_packing = 'shipping'
            elif packing_status == 'fully_packed':
                effective_packing = 'packed_waiting_ship'
            elif any_active_pick_printed and packing_status not in ('delivered',):
                # Chỉ "đã in, chờ đóng gói" khi PHIẾU PICK ĐANG ACTIVE đã được in.
                # Backorder PICK chưa in → rơi về packing_status (waiting_stock/unpacked).
                effective_packing = 'printed_waiting'
            else:
                effective_packing = packing_status

            if filter_packing_status in ('printed_waiting', 'packed_waiting_ship', 'shipping', 'delivered_today'):
                packing_ok = effective_packing == filter_packing_status
            else:
                packing_ok = filter_packing_status == 'all' or packing_status == filter_packing_status

            # --- New: Tình trạng phiếu in (per-column filter on Bảng) ---
            if filter_print_status == 'has_unprinted':
                print_ok = bool(active_pick_flows) and not any_active_pick_printed
            elif filter_print_status == 'all_printed':
                print_ok = bool(active_pick_flows) and any_active_pick_printed
            else:
                print_ok = True

            # --- New: Nhận giao (shipper_received) ---
            if filter_shipper_received == 'received':
                shipper_ok = bool(has_shipper)
            elif filter_shipper_received == 'not_received':
                shipper_ok = not bool(has_shipper)
            else:
                shipper_ok = True

            if filter_new_orders:
                order_date_raw = so_rec.get('x_studio_misa_order_date')
                if not order_date_raw:
                    d = so_rec.get('date_order')
                    order_date_raw = d.date() if d and hasattr(d, 'date') else None
                is_new = order_date_raw == today_date if order_date_raw else False
            else:
                is_new = True

            # Đơn đã giao trong ngày → bypass MỌI filter (delivery/packing/stock/print/
            # shipper/new/transfer). Đảm bảo cột "Đã giao trong ngày" luôn hiển thị
            # đầy đủ kể cả khi user đang lọc "Chưa giao & Giao 1 phần" hoặc các trạng
            # thái khác. Frontend sẽ tự xếp vào cột delivered_today dựa trên
            # has_delivered_today.
            if has_delivered_today:
                matched_sale_ids.append(so_id)
                continue

            if delivery_ok and packing_ok and is_new \
                    and (filter_stock_status == 'all' or stock_status == filter_stock_status) \
                    and (not filter_need_transfer or has_transfer_option) \
                    and print_ok and shipper_ok:
                matched_sale_ids.append(so_id)

        # KPI stats
        dashboard_stats = {
            'total': 0, 'ready': 0, 'partial': 0, 'out_of_stock': 0,
            'packing_fully': 0, 'packing_partial': 0, 'packing_unpacked': 0, 'packing_waiting': 0,
        }
        for so_id in matched_sale_ids:
            meta = so_meta_dict.get(so_id, {})
            st = meta.get('stock_status')
            ps = meta.get('packing_status')
            dashboard_stats['total'] += 1
            if st == 'ready':
                dashboard_stats['ready'] += 1
            elif st == 'partial_ready':
                dashboard_stats['partial'] += 1
            elif st == 'out_of_stock':
                dashboard_stats['out_of_stock'] += 1
            if meta.get('has_pending'):
                if ps == 'fully_packed':
                    dashboard_stats['packing_fully'] += 1
                elif ps == 'unpacked':
                    dashboard_stats['packing_unpacked'] += 1
                elif ps == 'waiting_stock':
                    dashboard_stats['packing_waiting'] += 1

        return sales, matched_sale_ids, dashboard_stats, product_availabilities, product_on_hand, so_status_dict
