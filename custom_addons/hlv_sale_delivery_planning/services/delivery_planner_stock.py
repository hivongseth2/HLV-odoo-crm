from odoo import models


class DeliveryPlannerServiceStock(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    def _calculate_po_and_stock_status(
        self, sales, po_date_from, po_date_to, po_status,
        filter_delivery_status, filter_stock_status, filter_packing_status,
        show_completed=False, filter_need_transfer=False,
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

        product_availabilities = {}
        wh_obj = self.env['stock.warehouse']
        for w_id, prod_ids in product_qty_cache.items():
            if prod_ids:
                wh = wh_obj.browse(w_id)
                loc_id = wh.lot_stock_id.id
                prods = self.env['product.product'].browse(list(prod_ids)).with_context(location=loc_id)
                # Odoo 18: free_qty = qty_available - reserved_quantity, scoped by location
                for p in prods:
                    product_availabilities[(p.id, w_id)] = p.free_qty

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
        all_order_lines = sales.mapped('order_line').filtered(
            lambda l: not l.display_type and l.product_id and l.product_id.type != 'service'
        )
        if all_order_lines:
            moves = self.env['stock.move'].sudo().search_read([
                ('sale_line_id', 'in', all_order_lines.ids),
                ('state', 'not in', ('cancel', 'done')),
            ], ['sale_line_id', 'quantity'])
            for m in moves:
                s_id = m['sale_line_id'][0]
                line_reserved_qty[s_id] = line_reserved_qty.get(s_id, 0.0) + m['quantity']

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
                    # 6a. Lấy free_qty tại các kho khác
                    missing_wh_loc_map = {}  # {wh_id: lot_stock_id}
                    for wh in all_db_warehouses.filtered(lambda w: w.id in missing_wh_ids):
                        if not wh.lot_stock_id:
                            continue
                        missing_wh_loc_map[wh.id] = wh.lot_stock_id.id
                        prods = self.env['product.product'].browse(
                            list(all_prod_ids_for_transfer)
                        ).with_context(location=wh.lot_stock_id.id)
                        for p in prods:
                            # Lưu cả free_qty = 0 để step 6b có thể cộng internal reserved
                            product_availabilities[(p.id, wh.id)] = p.free_qty

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

            # Khi không bật "hiện đơn đã giao": ẩn hoàn toàn các đơn này
            if not show_completed and no_active_outflow:
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
                if p_type == 'service' or is_kit:
                    continue

                has_storable_line = True
                if line.qty_delivered > 0:
                    has_delivered = True

                pending_qty = line.product_uom_qty - line.qty_delivered
                if pending_qty > 0:
                    has_pending = True
                    total_pending += pending_qty
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

            so_status_dict[so.id] = {
                'stock_status': stock_status,
                'packing_status': packing_status,
                'real_delivery_status': real_delivery_status,
                # Đơn trả hàng / dừng: outflow hết nhưng chưa giao đủ → hiện riêng khi show_completed
                'is_returned_or_stopped': no_active_outflow and real_delivery_status != 'full',
                # Đã in phiếu nhưng có phiếu pick mới chưa in (hàng về thêm)
                'has_new_unprinted_pickings': (
                    bool(so.x_picking_slip_printed)
                    and bool(active_outflow)
                    and any(
                        not p.x_printed
                        for p in active_outflow
                        if 'PICK' in (p.picking_type_id.sequence_code or '').upper()
                    )
                ),
                # Shipper đã nhận hàng giao chưa
                'has_shipper_received': has_shipper_received,
            }

            # Giữ metadata để tổng hợp KPI theo tập đã lọc cuối cùng.
            so_meta_dict[so.id] = {
                'stock_status': stock_status,
                'packing_status': packing_status,
                'has_pending': has_pending,
                'has_transfer_option': has_transfer_option,
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

            # Tính effective_packing_status bao gồm trạng thái in phiếu + shipper
            has_new_unprinted = so_status_dict[so.id].get('has_new_unprinted_pickings', False)
            has_shipper = so_status_dict[so.id].get('has_shipper_received', False)

            if has_shipper:
                # Shipper đã nhận → "Đang giao" (ưu tiên cao nhất)
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

            if filter_packing_status in ('has_unprinted', 'printed_waiting', 'packed_waiting_ship', 'shipping'):
                packing_ok = effective_packing == filter_packing_status
            else:
                packing_ok = filter_packing_status == 'all' or packing_status == filter_packing_status

            if (
                delivery_ok
                and (filter_stock_status == 'all' or stock_status == filter_stock_status)
                and packing_ok
                and (not filter_need_transfer or has_transfer_option)
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
