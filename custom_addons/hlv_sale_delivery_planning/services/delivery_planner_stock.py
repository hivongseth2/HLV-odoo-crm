from odoo import models


class DeliveryPlannerServiceStock(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    def _calculate_po_and_stock_status(
        self, sales, po_date_from, po_date_to, po_status,
        filter_delivery_status, filter_stock_status, filter_packing_status,
        show_completed=False, filter_need_transfer=False,
        filter_new_orders=False,
        filter_done_date_from='', filter_done_date_to='',
    ):
        """
        Lọc SO theo PO (nếu có filter PO), tính stock_status và packing_status
        cho từng SO, trả về danh sách ID khớp và dashboard stats.
        """
        # --- 1. Lọc theo tiêu chí PO (nếu có) ---
        if po_date_from or po_date_to or (po_status and po_status != 'all'):
            po_domain = [('origin', 'in', sales.mapped('name'))]
            if po_date_from:
                po_domain.append(('date_planned', '>=', po_date_from))
            if po_date_to:
                po_domain.append(('date_planned', '<=', po_date_to + ' 23:59:59'))
            if po_status and po_status != 'all':
                po_domain.append(('receipt_status', '=', po_status))

            matching_pos = self.env['purchase.order'].search_read(po_domain, ['origin'])
            origins = list(set([po['origin'] for po in matching_pos if po['origin']]))
            sales = sales.filtered(lambda s: s.name in origins)

        # --- 1b. Lọc theo ngày hoàn thành (date_done của phiếu OUT) ---
        if filter_done_date_from or filter_done_date_to:
            import pytz
            from datetime import datetime
            _tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'Asia/Ho_Chi_Minh')
            picking_domain = [
                ('picking_type_code', '=', 'outgoing'),
                ('state', '=', 'done'),
                ('sale_id', 'in', sales.ids),
            ]
            if filter_done_date_from:
                local_from = _tz.localize(datetime.strptime(filter_done_date_from, '%Y-%m-%d'))
                utc_from = local_from.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
                picking_domain.append(('date_done', '>=', utc_from))
            if filter_done_date_to:
                local_to = _tz.localize(datetime.strptime(filter_done_date_to, '%Y-%m-%d').replace(
                    hour=23, minute=59, second=59))
                utc_to = local_to.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
                picking_domain.append(('date_done', '<=', utc_to))
            done_pickings = self.env['stock.picking'].search(picking_domain)
            done_so_ids = set(done_pickings.mapped('sale_id').ids)
            sales = sales.filtered(lambda s: s.id in done_so_ids)

        all_order_lines = sales.mapped('order_line').filtered(
            lambda l: not l.display_type and l.product_id and l.product_id.type != 'service'
        )
        active_moves = self.env['stock.move'].sudo().search([
            ('sale_line_id', 'in', all_order_lines.ids),
            ('state', 'not in', ('cancel', 'done')),
        ])

        # --- 2. Tính tồn kho khả dụng theo kho + sản phẩm ---
        product_qty_cache = {}
        for so in sales:
            if so.warehouse_id:
                w_id = so.warehouse_id.id
                if w_id not in product_qty_cache:
                    product_qty_cache[w_id] = set()
                for line in so.order_line:
                    if not line.display_type and line.product_id:
                        product_qty_cache[w_id].add(line.product_id.id)
                # Bổ sung các sản phẩm thành phần của Combo/Kit
                for move in active_moves.filtered(lambda m: m.sale_line_id.order_id.id == so.id):
                    if move.product_id:
                        product_qty_cache[w_id].add(move.product_id.id)

        product_availabilities = {}
        wh_obj = self.env['stock.warehouse']
        # FIX #2: Thay vì gọi p.free_qty (N+1 queries), batch query qua stock.quant một lần.
        # stock.quant lưu (product_id, location_id, qty_on_hand, reserved_quantity).
        # free_qty = sum(quantity) - sum(reserved_quantity) per (product_id, location_id).
        for w_id, prod_ids in product_qty_cache.items():
            if not prod_ids:
                continue
            wh = wh_obj.browse(w_id)
            loc_id = wh.lot_stock_id.id
            # Lấy tất cả location con của kho (stock + sub-locations)
            child_loc_ids = self.env['stock.location'].sudo().search([
                ('id', 'child_of', loc_id), ('usage', '=', 'internal'),
            ]).ids
            if not child_loc_ids:
                child_loc_ids = [loc_id]
            quant_data = self.env['stock.quant'].sudo().read_group(
                domain=[
                    ('product_id', 'in', list(prod_ids)),
                    ('location_id', 'in', child_loc_ids),
                ],
                fields=['product_id', 'quantity:sum', 'reserved_quantity:sum'],
                groupby=['product_id'],
            )
            for row in quant_data:
                pid = row['product_id'][0]
                free = (row.get('quantity', 0.0) or 0.0) - (row.get('reserved_quantity', 0.0) or 0.0)
                product_availabilities[(pid, w_id)] = max(free, 0.0)
            # Sản phẩm không có trong quant → set = 0
            for pid in prod_ids:
                if (pid, w_id) not in product_availabilities:
                    product_availabilities[(pid, w_id)] = 0.0

        # --- 2b. Cộng lại qty đang bị giữ bởi internal transfers (không phải SO) ---
        # Lý do: SO ưu tiên hơn internal transfer, nên hàng bị internal giữ
        # vẫn tính là "có hàng" cho SO (Odoo sẽ unreserve internal khi cần).
        all_prod_ids = set()
        wh_loc_map = {}  # {warehouse_id: lot_stock_id}
        for w_id, prod_ids in product_qty_cache.items():
            wh = wh_obj.browse(w_id)
            wh_loc_map[w_id] = wh.lot_stock_id.id
            all_prod_ids.update(prod_ids)

        if all_prod_ids and wh_loc_map:
            # Pre-cache: tất cả child locations của từng warehouse
            loc_to_wh = {}  # {location_id: warehouse_id}
            for w_id, loc_id in wh_loc_map.items():
                child_locs = self.env['stock.location'].sudo().search([
                    ('id', 'child_of', loc_id),
                ])
                for cl in child_locs:
                    loc_to_wh[cl.id] = w_id

            internal_moves = self.env['stock.move'].sudo().search_read([
                ('product_id', 'in', list(all_prod_ids)),
                ('state', 'in', ('assigned', 'partially_available')),
                ('picking_id.picking_type_code', '=', 'internal'),
                ('picking_id.state', 'not in', ('done', 'cancel')),
                ('sale_line_id', '=', False),
            ], ['product_id', 'location_id', 'quantity'])

            for mv in internal_moves:
                pid = mv['product_id'][0]
                mv_loc_id = mv['location_id'][0]
                w_id = loc_to_wh.get(mv_loc_id)
                if w_id and (pid, w_id) in product_availabilities:
                    product_availabilities[(pid, w_id)] += mv['quantity']

        # --- 3. Số lượng đang giữ (reserved) theo dòng SO ---
        line_reserved_qty = {}
        for m in active_moves:
            s_id = m.sale_line_id.id
            line_reserved_qty[s_id] = line_reserved_qty.get(s_id, 0.0) + m.quantity

        # --- 4. Tính số lượng đã đóng gói theo PHẦN CÒN PENDING của từng dòng SO ---
        # Mục tiêu: không để hàng đã giao xong ở các dòng khác làm phình packed_qty của đơn.
        pending_qty_by_line = {}
        for line in sales.mapped('order_line'):
            if line.display_type or not line.product_id:
                continue
            if line.product_id.type == 'service':
                continue
            pending_qty = line.product_uom_qty - line.qty_delivered
            if pending_qty > 0:
                pending_qty_by_line[line.id] = pending_qty

        all_picking_ids = sales.mapped('picking_ids').ids
        packed_qty_by_so = {}
        if all_picking_ids and pending_qty_by_line:
            mls = self.env['stock.move.line'].sudo().search([
                ('picking_id', 'in', all_picking_ids),
                ('picking_id.picking_type_code', '=', 'outgoing'),
                ('picking_id.state', 'not in', ['done', 'cancel']),
                ('result_package_id', '!=', False),
                ('state', 'not in', ['cancel', 'draft']),
                ('move_id.sale_line_id', 'in', list(pending_qty_by_line.keys())),
            ])

            # Gộp theo line để có thể cap theo pending từng dòng.
            packed_by_line = {}
            so_by_line = {}
            for ml in mls:
                line_id = ml.move_id.sale_line_id.id
                if not line_id:
                    continue
                so_id = ml.picking_id.sale_id.id if ml.picking_id.sale_id else False
                if not so_id:
                    continue
                packed_by_line[line_id] = packed_by_line.get(line_id, 0.0) + float(ml.quantity)
                so_by_line[line_id] = so_id

            for line_id, packed_qty in packed_by_line.items():
                so_id = so_by_line.get(line_id)
                if not so_id:
                    continue
                capped_qty = min(packed_qty, pending_qty_by_line.get(line_id, 0.0))
                packed_qty_by_so[so_id] = packed_qty_by_so.get(so_id, 0.0) + capped_qty

        # --- 5. Nhận diện sản phẩm Kit (phantom BOM) ---
        all_product_tmpl_ids = sales.mapped('order_line.product_id.product_tmpl_id').ids
        kits = self.env['mrp.bom'].sudo().search([
            ('product_tmpl_id', 'in', all_product_tmpl_ids),
            ('type', '=', 'phantom'),
        ])
        kit_tmpl_ids = set(kits.mapped('product_tmpl_id').ids)

        # --- 6. Tính stock_status + packing_status cho từng SO ---
        # Tập warehouse IDs để kiểm tra chuyển kho nhanh (kh&ocirc;ng query th&ecirc;m)
        # Phải l&agrave; TẤT CẢ c&aacute;c kho, kh&ocirc;ng chỉ c&aacute;c kho trong filter,
        # để filter_need_transfer hoạt động đ&uacute;ng khi kết hợp với filter kho.
        all_warehouse_ids = set(k[1] for k in product_availabilities.keys())

        if all_warehouse_ids:
            # Bổ sung inventory cho c&aacute;c kho kh&aacute;c chưa c&oacute; trong product_availabilities
            # (xảy ra khi đang filter theo 1 kho cụ thể)
            all_db_warehouses = self.env['stock.warehouse'].search([])
            missing_wh_ids = set(all_db_warehouses.ids) - all_warehouse_ids
            if missing_wh_ids:
                # Thu thập tất cả product_id đang cần check
                all_prod_ids_for_transfer = set(k[0] for k in product_availabilities.keys())
                if all_prod_ids_for_transfer:
                    # 6a. Lấy free_qty tại các kho khác — dùng stock.quant batch (không N+1)
                    missing_wh_loc_map = {}  # {wh_id: lot_stock_id}
                    for wh in all_db_warehouses.filtered(lambda w: w.id in missing_wh_ids):
                        if not wh.lot_stock_id:
                            continue
                        missing_wh_loc_map[wh.id] = wh.lot_stock_id.id
                        child_loc_ids = self.env['stock.location'].sudo().search([
                            ('id', 'child_of', wh.lot_stock_id.id), ('usage', '=', 'internal'),
                        ]).ids or [wh.lot_stock_id.id]
                        quant_rows = self.env['stock.quant'].sudo().read_group(
                            domain=[
                                ('product_id', 'in', list(all_prod_ids_for_transfer)),
                                ('location_id', 'in', child_loc_ids),
                            ],
                            fields=['product_id', 'quantity:sum', 'reserved_quantity:sum'],
                            groupby=['product_id'],
                        )
                        quant_map = {r['product_id'][0]: max(
                            (r.get('quantity') or 0.0) - (r.get('reserved_quantity') or 0.0), 0.0
                        ) for r in quant_rows}
                        for pid in all_prod_ids_for_transfer:
                            # Lưu cả free_qty = 0 để step 6b có thể cộng internal reserved
                            product_availabilities[(pid, wh.id)] = quant_map.get(pid, 0.0)

                    # 6b. Cộng lại internal transfer reserved (giống step 2b)
                    # vì SO ưu tiên hơn internal transfer
                    if missing_wh_loc_map:
                        missing_loc_to_wh = {}
                        for w_id, loc_id in missing_wh_loc_map.items():
                            child_locs = self.env['stock.location'].sudo().search([
                                ('id', 'child_of', loc_id),
                            ])
                            for cl in child_locs:
                                missing_loc_to_wh[cl.id] = w_id

                        missing_internal_moves = self.env['stock.move'].sudo().search_read([
                            ('product_id', 'in', list(all_prod_ids_for_transfer)),
                            ('state', 'in', ('assigned', 'partially_available')),
                            ('picking_id.picking_type_code', '=', 'internal'),
                            ('picking_id.state', 'not in', ('done', 'cancel')),
                            ('sale_line_id', '=', False),
                        ], ['product_id', 'location_id', 'quantity'])

                        for mv in missing_internal_moves:
                            pid = mv['product_id'][0]
                            mv_loc_id = mv['location_id'][0]
                            w_id = missing_loc_to_wh.get(mv_loc_id)
                            if w_id and (pid, w_id) in product_availabilities:
                                product_availabilities[(pid, w_id)] += mv['quantity']

                    # Xóa entries <= 0 tại kho khác để không gây nhiễu
                    to_remove = [
                        k for k in product_availabilities
                        if k[1] in missing_wh_ids and product_availabilities[k] <= 0
                    ]
                    for k in to_remove:
                        del product_availabilities[k]

                    all_warehouse_ids = set(k[1] for k in product_availabilities.keys())

        matched_sale_ids = []
        dashboard_stats = {
            'total': 0, 'ready': 0, 'partial': 0, 'out_of_stock': 0,
            'packing_fully': 0, 'packing_partial': 0,
            'packing_unpacked': 0, 'packing_waiting': 0,
        }
        so_status_dict = {}
        so_meta_dict = {}

        # Tính today 1 lần ngoài vòng lặp cho filter_new_orders + delivered_today
        from odoo.fields import Date as OdooDate
        from odoo.fields import Datetime as OdooDatetime
        import pytz
        today_date = OdooDate.context_today(self)
        # Timezone để convert date_done (UTC) sang local date
        user_tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'Asia/Ho_Chi_Minh')

        # FIX #3: Prefetch toàn bộ các field cần trong vòng lặp chính — batch 1 SQL mỗi field.
        # Không prefetch: mỗi so.picking_ids trong loop = 1 query riêng.
        # Core fields luôn tồn tại trên stock.picking
        picking_core_fields = [
            'state', 'picking_type_code', 'picking_type_id', 'return_id',
            'date_done', 'sale_id', 'move_ids',
        ]
        # Optional fields từ module hlv_sale_delivery_planning / hlv_barcode_shipper
        picking_optional_fields = ['x_printed', 'shipper_received', 'shipper_returned', 'shipper_received_by']
        picking_model_fields = set(self.env['stock.picking']._fields.keys())
        picking_safe_fields = picking_core_fields + [
            f for f in picking_optional_fields if f in picking_model_fields
        ]

        all_pickings = sales.mapped('picking_ids')
        if all_pickings:
            all_pickings.read(picking_safe_fields)     # batch-load vào cache
            all_pickings.mapped('picking_type_id').read(['sequence_code', 'code'])
            # Prefetch move_ids fields để tránh lazy load trong loop
            all_pickings.mapped('move_ids').read(['state', 'product_id', 'quantity', 'product_uom_qty', 'sale_line_id'])

        # Prefetch order_line fields
        sales.mapped('order_line').read([
            'product_id', 'product_uom_qty', 'qty_delivered', 'display_type',
        ])

        for so in sales:
            # --- Phát hiện đơn "trả hàng / dừng": không còn outflow nào active ---
            # Luồng xuất = pick/pack/out (code = internal hoặc outgoing), loại trừ phiếu nhập (incoming).
            # Phiếu trả hàng (return_id != False) không tính là outflow thật — chúng chỉ đảo ngược hàng.
            active_outflow = so.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel')
                and p.picking_type_code in ('outgoing', 'internal')
                and not p.return_id  # Loại bỏ phiếu trả hàng
            )
            has_any_outflow = any(
                p.picking_type_code in ('outgoing', 'internal') and not p.return_id
                for p in so.picking_ids
            )
            # Đơn "trả hàng / dừng": đã từng có outflow nhưng không còn cái nào active
            no_active_outflow = has_any_outflow and not bool(active_outflow)

            # Tính has_delivered_today SỚM (trước no_active_outflow skip)
            # date_done lưu UTC → convert sang timezone local trước khi so sánh ngày
            has_delivered_today = any(
                p.state == 'done'
                and p.date_done
                and p.date_done.replace(tzinfo=pytz.utc).astimezone(user_tz).date() == today_date
                for p in so.picking_ids
                if p.picking_type_code == 'outgoing' and not p.return_id
            )

            # Khi không bật "hiện đơn đã giao": ẩn hoàn toàn các đơn này
            # NGOẠI TRỪ: đơn có phiếu OUT done hôm nay → hiện trong cột "Đã giao trong ngày"
            # NGOẠI TRỪ: user đang filter theo ngày hoàn thành → đơn đã pass filter 1b
            if not show_completed and no_active_outflow and not has_delivered_today \
                    and not filter_done_date_from and not filter_done_date_to:
                continue

            has_pending = False
            has_delivered = False
            has_storable_line = False
            is_fully_ready = True
            total_pending, total_avail = 0, 0

            for line in so.order_line:
                if line.display_type or not line.product_id:
                    continue
                p_type = line.product_id.type
                is_kit = line.product_id.product_tmpl_id.id in kit_tmpl_ids
                if p_type == 'service':
                    continue

                has_storable_line = True
                if line.qty_delivered > 0:
                    has_delivered = True

                pending_qty = line.product_uom_qty - line.qty_delivered
                if pending_qty > 0:
                    has_pending = True
                    total_pending += pending_qty
                    
                    if is_kit:
                        # Bóc tách thành phần của Kit từ active_moves đã duyệt
                        cmp_moves = active_moves.filtered(lambda m: m.sale_line_id.id == line.id)
                        if not cmp_moves:
                            is_fully_ready = False
                        else:
                            for cm in cmp_moves:
                                c_pending = cm.product_uom_qty
                                if c_pending > 0:
                                    c_base_free = product_availabilities.get((cm.product_id.id, so.warehouse_id.id), 0.0)
                                    c_reserved = cm.quantity
                                    c_avail = c_base_free + c_reserved
                                    if c_avail > 0:
                                        total_avail += min(c_avail, c_pending)
                                    if c_avail < c_pending:
                                        is_fully_ready = False
                    else:
                        base_free = product_availabilities.get(
                            (line.product_id.id, so.warehouse_id.id), 0.0
                        )
                        reserved_here = line_reserved_qty.get(line.id, 0.0)
                        qty_avail = base_free + reserved_here
                        if qty_avail > 0:
                            total_avail += min(qty_avail, pending_qty)
                        if qty_avail < pending_qty:
                            is_fully_ready = False

            if has_pending:
                stock_status = 'ready' if is_fully_ready else (
                    'partial_ready' if total_avail > 0 else 'out_of_stock'
                )
            else:
                stock_status = 'delivered'

            # Kiểm tra nhanh: có kho khác tồn trữ sản phẩm đang thiếu không?
            # Dùng product_availabilities đã tính sẵn → không tốn thêm query.
            # QUAN TRỌNG: phải check products_with_active_demand (giống _compute_transfer_suggestions)
            # để đảm bảo filter "Cần chuyển kho" khớp với đề xuất trong drawer.
            has_transfer_option = False
            if filter_need_transfer and stock_status != 'ready':
                dest_wh_id = so.warehouse_id.id
                # Chỉ xét SP có stock move active trong picking (khớp formatter)
                active_pks = so.picking_ids.filtered(
                    lambda p: p.state not in ('done', 'cancel') and not p.return_id
                )
                products_with_demand = set()
                for pk in active_pks:
                    for mv in pk.move_ids:
                        if mv.state not in ('cancel', 'done'):
                            products_with_demand.add(mv.product_id.id)

                for line in so.order_line:
                    if line.display_type or not line.product_id:
                        continue
                    if line.product_id.type == 'service':
                        continue
                    if line.product_id.product_tmpl_id.id in kit_tmpl_ids:
                        continue
                    if line.product_id.id not in products_with_demand:
                        continue
                    pending_qty = line.product_uom_qty - line.qty_delivered
                    if pending_qty <= 0:
                        continue
                    qty_at_dest = (product_availabilities.get((line.product_id.id, dest_wh_id), 0.0)
                                   + line_reserved_qty.get(line.id, 0.0))
                    if qty_at_dest >= pending_qty:
                        continue  # đủ hàng tại kho đích cho dòng này
                    # Thiếu → check kho khác
                    for other_wh_id in all_warehouse_ids:
                        if other_wh_id != dest_wh_id:
                            if product_availabilities.get((line.product_id.id, other_wh_id), 0.0) > 0:
                                has_transfer_option = True
                                break
                    if has_transfer_option:
                        break

            # Dong bo voi logic hien thi tren card/kanban.
            if not has_storable_line:
                real_delivery_status = 'full'
            elif has_pending and not has_delivered:
                real_delivery_status = 'unshipped'
            elif has_pending and has_delivered:
                real_delivery_status = 'partial'
            else:
                real_delivery_status = 'full'

            packed_qty = packed_qty_by_so.get(so.id, 0.0)
            # Packing status dựa trên trạng thái phiếu kho (PACK/OUT), không còn dựa trên package.
            # Lý do: nhiều phiếu sản phẩm không nằm trong kiện hàng nhưng đã qua bước đóng gói.
            if not has_pending:
                packing_status = 'delivered'
            elif total_avail <= 0:
                packing_status = 'waiting_stock'
            else:
                # Kiểm tra trạng thái phiếu PACK và OUT
                pack_pickings = active_outflow.filtered(
                    lambda p: (p.picking_type_id.sequence_code or '').upper() == 'PACK'
                )
                out_pickings = active_outflow.filtered(
                    lambda p: (p.picking_type_id.sequence_code or '').upper() == 'OUT'
                )
                # Phiếu PACK đã done (không còn trong active_outflow) → check tất cả pickings
                done_pack = so.picking_ids.filtered(
                    lambda p: p.state == 'done'
                    and not p.return_id
                    and (p.picking_type_id.sequence_code or '').upper() == 'PACK'
                )
                # Nếu có phiếu PACK đã done VÀ không còn phiếu PACK active → đã đóng gói xong
                # Hoặc: không có PACK (2-step) mà PICK đã done → cũng tính là packed
                if done_pack and not pack_pickings:
                    packing_status = 'fully_packed'
                elif not done_pack and not pack_pickings and not out_pickings:
                    # Không có phiếu nào active ngoài PICK → chưa đến bước pack
                    packing_status = 'unpacked'
                else:
                    # Còn phiếu PACK active → đang đóng gói
                    packing_status = 'unpacked'

            # Shipper đã nhận hàng để giao? (chỉ xét outgoing pickings)
            has_shipper_received = any(
                p.shipper_received and not p.shipper_returned
                for p in active_outflow
                if p.picking_type_code == 'outgoing'
            )

            # has_delivered_today đã tính ở trên (trước no_active_outflow skip)

            so_status_dict[so.id] = {
                'stock_status': stock_status,
                'packing_status': packing_status,
                'real_delivery_status': real_delivery_status,
                # Đơn trả hàng / dừng: outflow hết nhưng chưa giao đủ → hiện riêng khi show_completed
                'is_returned_or_stopped': no_active_outflow and real_delivery_status != 'full',
                # Đã in phiếu nhưng có phiếu pick mới chưa in VÀ có hàng (assigned).
                # Nếu phiếu PICK chưa in nhưng chưa có hàng (confirmed/waiting) → không ưu tiên trạng thái này.
                'has_new_unprinted_pickings': (
                    bool(so.x_picking_slip_printed)
                    and bool(active_outflow)
                    and any(
                        not p.x_printed and p.state == 'assigned'
                        for p in active_outflow
                        if 'PICK' in (p.picking_type_id.sequence_code or '').upper()
                    )
                ),
                # Shipper đã nhận hàng giao chưa
                'has_shipper_received': has_shipper_received,
                # Đã giao hàng (OUT done) trong ngày hôm nay
                'has_delivered_today': has_delivered_today,
                # Có phiếu PICK nào đang ASSIGNED (sẵn hàng thực sự) không
                # (dùng để quyết định có nên ưu tiên delivered_today hay không)
                'has_assigned_pick': any(
                    p.state == 'assigned'
                    for p in active_outflow
                    if 'PICK' in (p.picking_type_id.sequence_code or '').upper()
                ),
            }

            # Giữ metadata để tổng hợp KPI theo tập đã lọc cuối cùng.
            so_meta_dict[so.id] = {
                'stock_status': stock_status,
                'packing_status': packing_status,
                'has_pending': has_pending,
                'has_transfer_option': has_transfer_option,
                'has_unread_message': bool(so.x_plan_unread_message if hasattr(so, 'x_plan_unread_message') else False),
            }

            is_returned_or_stopped = so_status_dict[so.id]['is_returned_or_stopped']

            # Đơn trả hàng/dừng: hiển thị riêng trong group "Trả hàng" khi show_completed
            if show_completed and is_returned_or_stopped:
                matched_sale_ids.append(so.id)
                continue

            if filter_delivery_status == 'pending_partial':
                delivery_ok = real_delivery_status in ('unshipped', 'partial')
            elif filter_delivery_status in ('unshipped', 'pending'):
                delivery_ok = real_delivery_status == 'unshipped'
            elif filter_delivery_status in ('partial', 'full'):
                delivery_ok = real_delivery_status == filter_delivery_status
            else:
                delivery_ok = True

            # NẾU USER CỐ TÌNH FILTER MỤC HOÀN THÀNH TỪ/ĐẾN
            if filter_done_date_from or filter_done_date_to:
                done_outflows = so.picking_ids.filtered(lambda p: p.state == 'done' and p.date_done)
                if not done_outflows:
                    delivery_ok = False
                else:
                    latest_done = max(done_outflows, key=lambda p: p.date_done)
                    latest_done_str = latest_done.date_done.replace(tzinfo=pytz.utc).astimezone(user_tz).strftime('%Y-%m-%d')
                    if filter_done_date_from and latest_done_str < filter_done_date_from:
                        delivery_ok = False
                    elif filter_done_date_to and latest_done_str > filter_done_date_to:
                        delivery_ok = False
                    else:
                        delivery_ok = True

            # Tính effective_packing_status bao gồm trạng thái in phiếu + shipper
            has_new_unprinted = so_status_dict[so.id].get('has_new_unprinted_pickings', False)
            has_shipper = so_status_dict[so.id].get('has_shipper_received', False)
            delivered_today = so_status_dict[so.id].get('has_delivered_today', False)

            # Kiểm tra có phiếu PICK nào đang ASSIGNED (sẵn hàng thực sự) không
            has_assigned_pick = any(
                p.state == 'assigned'
                for p in active_outflow
                if 'PICK' in (p.picking_type_id.sequence_code or '').upper()
            )

            # delivered_today: ưu tiên CAO NHẤT khi:
            #   - Có phiếu OUT done hôm nay (kể cả đơn giao partial)
            #   - VÀ không có phiếu PICK nào đang assigned sẵn hàng
            # Lý do: nếu PICK chỉ confirmed/waiting = đợi hàng về, không cần làm gì ngay.
            if delivered_today and (real_delivery_status == 'full' or not has_assigned_pick):
                effective_packing = 'delivered_today'
                # Bypass delivery filter – luôn show "Đã giao trong ngày"
                delivery_ok = True
            elif has_shipper:
                # Shipper đã nhận → "Đang giao"
                effective_packing = 'shipping'
            elif has_new_unprinted:
                effective_packing = 'has_unprinted'
            elif packing_status == 'fully_packed':
                # Đã đóng gói đủ, shipper chưa nhận → "Đã gói, chờ nhận giao"
                effective_packing = 'packed_waiting_ship'
            elif bool(so.x_picking_slip_printed) and packing_status not in ('delivered',):
                effective_packing = 'printed_waiting'
            else:
                effective_packing = packing_status

            if filter_packing_status in ('has_unprinted', 'printed_waiting', 'packed_waiting_ship', 'shipping', 'delivered_today'):
                packing_ok = effective_packing == filter_packing_status
            else:
                packing_ok = filter_packing_status == 'all' or packing_status == filter_packing_status

            # Kiểm tra đơn hàng mới (misa_order_date hoặc date_order = hôm nay)
            if filter_new_orders:
                order_date = so.x_studio_misa_order_date or (so.date_order.date() if so.date_order else None)
                is_new = order_date == today_date if order_date else False
            else:
                is_new = True  # Không filter → cho qua

            if (
                delivery_ok
                and (filter_stock_status == 'all' or stock_status == filter_stock_status)
                and packing_ok
                and (not filter_need_transfer or has_transfer_option)
                and is_new
            ):
                matched_sale_ids.append(so.id)

        # KPI phải phản ánh đúng tập dữ liệu sau khi áp toàn bộ filter hiện tại.
        dashboard_stats.update({
            'total': 0,
            'ready': 0,
            'partial': 0,
            'out_of_stock': 0,
            'packing_fully': 0,
            'packing_partial': 0,
            'packing_unpacked': 0,
            'packing_waiting': 0,
        })

        for so_id in matched_sale_ids:
            meta = so_meta_dict.get(so_id, {})
            stock_status = meta.get('stock_status')
            packing_status = meta.get('packing_status')
            has_pending = meta.get('has_pending', False)

            dashboard_stats['total'] += 1
            if stock_status == 'ready':
                dashboard_stats['ready'] += 1
            elif stock_status == 'partial_ready':
                dashboard_stats['partial'] += 1
            elif stock_status == 'out_of_stock':
                dashboard_stats['out_of_stock'] += 1

            if has_pending:
                if packing_status == 'fully_packed':
                    dashboard_stats['packing_fully'] += 1
                elif packing_status == 'unpacked':
                    dashboard_stats['packing_unpacked'] += 1
                elif packing_status == 'waiting_stock':
                    dashboard_stats['packing_waiting'] += 1

        return sales, matched_sale_ids, dashboard_stats, product_availabilities, so_status_dict
