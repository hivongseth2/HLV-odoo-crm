from odoo import models


class DeliveryPlannerServiceFormatter(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    def _compute_transfer_suggestions(self, so, so_lines_data):
        """
        Đề xuất chuyển kho: tìm sản phẩm thiếu ở kho hiện tại
        nhưng có sẵn (chưa bị giữ bởi đơn khác) ở kho khác.
        Trả về list grouped by product:
        [{ product_id, product_name, shortage, sources: [{from_warehouse_id, from_warehouse_name, available_qty, suggested_qty}] }]
        """
        if not so.warehouse_id:
            return []

        # Chỉ đề xuất chuyển kho cho sản phẩm còn nằm trong phiếu pick/pack/out đang chờ/xử lý
        # (loại bỏ sản phẩm đã giao-trả mà không còn phiếu active nào)
        # Phiếu trả hàng (return_id) không tạo demand thật
        active_pickings = so.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel')
            and not p.return_id
        )
        products_with_active_demand = set()
        for pk in active_pickings:
            for mv in pk.move_ids.filtered(lambda m: m.state not in ('cancel', 'done')):
                products_with_active_demand.add(mv.product_id.id)

        # Thu thập sản phẩm thiếu (group theo product_id)
        shortage_map = {}
        for line_data in so_lines_data:
            if not line_data.get('product_id') or line_data.get('is_kit'):
                continue
            if line_data.get('product_type') == 'service':
                continue
            pid = line_data['product_id'][0]
            # Bỏ qua sản phẩm không còn phiếu active nào (đã giao + trả hàng)
            if pid not in products_with_active_demand:
                continue
            pending = line_data['product_uom_qty'] - line_data['qty_delivered']
            if pending <= 0:
                continue
            eff_stock = (line_data.get('qty_warehouse_free') or 0) + (line_data.get('qty_reserved_here') or 0)
            shortage = pending - eff_stock
            if shortage > 0:
                if pid in shortage_map:
                    shortage_map[pid]['shortage'] += shortage
                else:
                    shortage_map[pid] = {
                        'product_id': pid,
                        'product_name': line_data['product_id'][1],
                        'shortage': shortage,
                    }

        shortage_products = list(shortage_map.values())

        if not shortage_products:
            return []

        other_warehouses = self.env['stock.warehouse'].search([
            ('id', '!=', so.warehouse_id.id),
        ])
        if not other_warehouses:
            return []

        suggestions = []
        for sp in shortage_products:
            remaining = sp['shortage']
            sources = []
            for wh in other_warehouses:
                if remaining <= 0:
                    break
                quants = self.env['stock.quant'].sudo().search([
                    ('product_id', '=', sp['product_id']),
                    ('location_id', 'child_of', wh.lot_stock_id.id),
                ])
                available = sum(
                    max(float(q.quantity) - float(q.reserved_quantity), 0.0)
                    for q in quants
                )
                if available > 0:
                    suggest_qty = min(available, remaining)
                    sources.append({
                        'from_warehouse_id': wh.id,
                        'from_warehouse_name': wh.name,
                        'available_qty': available,
                        'suggested_qty': suggest_qty,
                    })
                    remaining -= suggest_qty
            if sources:
                suggestions.append({
                    'product_id': sp['product_id'],
                    'product_name': sp['product_name'],
                    'shortage': sp['shortage'],
                    'to_warehouse_name': so.warehouse_id.name,
                    'sources': sources,
                })

        return suggestions

    def _format_dashboard_order(
        self, so, po_by_origin, product_availabilities,
        att_by_picking, so_packages_dict, so_status_dict,
    ):
        """
        Serialize một Sale Order thành dict để trả về cho OWL Dashboard.
        Tính real_delivery_status, gom thông tin lines, pickings, packages.
        """
        # --- PO data ---
        pos = po_by_origin.get(so.name, [])
        po_data = [
            {
                'id': po.id, 'name': po.name, 'state': po.state,
                'receipt_status': po.receipt_status if hasattr(po, 'receipt_status') else 'unknown',
                'date_planned': po.date_planned.strftime('%Y-%m-%d %H:%M:%S') if po.date_planned else False,
                'partner_id': [po.partner_id.id, po.partner_id.name] if po.partner_id else False,
                'amount_total': po.amount_total,
            }
            for po in pos
        ]

        # --- Tổng số lượng đã đóng kiện theo tên sản phẩm ---
        qty_packed_map = {}
        total_packages_count = 0
        package_groups = so_packages_dict.get(so.id, [])
        for group in package_groups:
            for pack in group.get('packages', []):
                total_packages_count += 1
                for prod_name, qty in pack.get('product_map', {}).items():
                    qty_packed_map[prod_name] = qty_packed_map.get(prod_name, 0.0) + qty

        # --- Nhận diện Kit (phantom BOM) ---
        product_templates = so.order_line.mapped('product_id.product_tmpl_id')
        kits = self.env['mrp.bom'].sudo().search([
            ('product_tmpl_id', 'in', product_templates.ids),
            ('type', '=', 'phantom'),
        ])
        kit_tmpl_ids = set(kits.mapped('product_tmpl_id').ids)

        # Cache tồn kho thực (on_hand - reserved_in_quant) cho linh kiện kit
        # Dùng riêng vì product_availabilities dùng free_qty (bỏ qua assigned reservations)
        kit_comp_true_free = {}

        # --- Dòng sản phẩm ---
        has_pending = False
        has_delivered = False
        is_fully_ready = True
        so_lines_data = []
        remaining_free_by_product = {}

        for line in so.order_line:
            if line.display_type:
                continue

            p_name = line.product_id.display_name if line.product_id else 'Unknown'
            p_type = line.product_id.type if line.product_id else 'service'
            is_kit = line.product_id.product_tmpl_id.id in kit_tmpl_ids

            if is_kit:
                # Phantom BOM kit: tính số kit hoàn chỉnh có thể lắp ráp từ linh kiện
                bom = next(
                    (b for b in kits if b.product_tmpl_id.id == line.product_id.product_tmpl_id.id),
                    None
                )
                if bom and so.warehouse_id:
                    # Lấy pickings active của đơn này để cộng lại reserved cho chính đơn
                    so_active_pickings = so.picking_ids.filtered(
                        lambda p: p.state not in ('done', 'cancel')
                    )

                    kit_qty = float('inf')
                    for comp_line in bom.bom_line_ids:
                        comp_key = (comp_line.product_id.id, so.warehouse_id.id)
                        if comp_key not in kit_comp_true_free:
                            # Tính từ quants: quantity - reserved_quantity (tất cả reservations)
                            quants = self.env['stock.quant'].sudo().search([
                                ('product_id', '=', comp_line.product_id.id),
                                ('location_id', 'child_of', so.warehouse_id.lot_stock_id.id),
                            ])
                            kit_comp_true_free[comp_key] = sum(
                                max(float(q.quantity) - float(q.reserved_quantity), 0.0)
                                for q in quants
                            )
                        # Tìm phần đã reserve cho chính đơn này
                        # (cộng lại vì đã bị trừ trong quants nhưng thực ra là của đơn này)
                        comp_reserved_for_so = sum(
                            float(mv.quantity)
                            for pk in so_active_pickings
                            for mv in pk.move_ids
                            if mv.product_id.id == comp_line.product_id.id
                            and mv.state not in ('cancel', 'done')
                        )
                        comp_free = kit_comp_true_free[comp_key] + comp_reserved_for_so
                        qty_per_kit = comp_line.product_qty / (bom.product_qty or 1.0)
                        if qty_per_kit > 0:
                            kit_qty = min(kit_qty, comp_free / qty_per_kit)
                    qty_avail = kit_qty if kit_qty != float('inf') else 0.0
                else:
                    qty_avail = 0.0
            else:
                product_wh_key = False
                if line.product_id and so.warehouse_id:
                    product_wh_key = (line.product_id.id, so.warehouse_id.id)
                    if product_wh_key not in remaining_free_by_product:
                        remaining_free_by_product[product_wh_key] = product_availabilities.get(product_wh_key, 0.0)

                base_free_remaining = remaining_free_by_product.get(product_wh_key, 0.0) if product_wh_key else 0.0
                reserved_here = sum(
                    line.move_ids.filtered(lambda m: m.state not in ('cancel', 'done')).mapped('quantity')
                )
                pending_qty_line = max(line.product_uom_qty - line.qty_delivered, 0.0)
                allocated_free = min(base_free_remaining, pending_qty_line) if pending_qty_line > 0 else 0.0
                qty_avail = allocated_free + reserved_here
                if product_wh_key and allocated_free > 0:
                    remaining_free_by_product[product_wh_key] = max(base_free_remaining - allocated_free, 0.0)
            qty_packed = qty_packed_map.get(p_name, 0.0)

            # Raw warehouse free_qty (không capped theo line) để hiển thị "Tồn Kho"
            if is_kit:
                raw_free = qty_avail  # Kit giữ nguyên logic kit
                reserved_line = 0.0  # Kit qty_avail đã bao gồm reservations rồi
            elif product_wh_key:
                raw_free = product_availabilities.get(product_wh_key, 0.0)
                reserved_line = reserved_here  # reuse biến đã tính ở trên
            else:
                raw_free = 0.0
                reserved_line = 0.0

            so_lines_data.append({
                'id': line.id,
                'product_id': [line.product_id.id, p_name] if line.product_id else False,
                'product_uom_qty': line.product_uom_qty,
                'qty_delivered': line.qty_delivered,
                'qty_packed': qty_packed,
                'qty_available': qty_avail,
                'qty_warehouse_free': raw_free,
                'qty_reserved_here': reserved_line,
                'product_type': p_type,
                'is_kit': is_kit,
            })

            if p_type != 'service' and not is_kit:
                pending_qty = line.product_uom_qty - line.qty_delivered
                if pending_qty > 0:
                    has_pending = True
                    if qty_avail < pending_qty:
                        is_fully_ready = False
                if line.qty_delivered > 0:
                    has_delivered = True

        # --- Stock + packing status từ dict đã tính sẵn ---
        packing_status = so_status_dict.get('packing_status', 'unknown')
        stock_status = so_status_dict.get('stock_status', 'out_of_stock')

        # --- Real delivery status ---
        # Uu tien gia tri da tinh o service stock de dong bo voi filter backend.
        storable_lines = [l for l in so_lines_data if l.get('product_type') != 'service']
        if not storable_lines:
            fallback_real_delivery_status = 'full'
        elif has_pending and not has_delivered:
            fallback_real_delivery_status = 'unshipped'
        elif has_pending and has_delivered:
            fallback_real_delivery_status = 'partial'
        else:
            fallback_real_delivery_status = 'full'
        real_delivery_status = so_status_dict.get('real_delivery_status', fallback_real_delivery_status)

        # --- Phiếu kho (flat list, sắp xếp theo thời gian) ---
        flat_pickings = []
        for p in sorted(
            so.picking_ids,
            key=lambda p: (p.date_done or p.scheduled_date or p.create_date, p.id),
        ):
            flat_pickings.append({
                'id': p.id, 'name': p.name, 'state': p.state,
                'type_name': p.picking_type_id.name or '',
                'code': p.picking_type_id.code or '',
                'scheduled_date': p.scheduled_date.strftime('%Y-%m-%d') if p.scheduled_date else False,
                'backorder_of': p.backorder_id.name if p.backorder_id else False,
                'return_of_id': p.return_id.id if p.return_id else False,
                'return_of': p.return_id.name if p.return_id else False,
                'printed': bool(p.x_printed),
                'videos': att_by_picking.get(p.id, []),
            })

        flows = self._build_flow_nodes(so, att_by_picking)
        picking_warehouse_ids = list(set([
            p.picking_type_id.warehouse_id.id
            for p in so.picking_ids
            if p.picking_type_id and p.picking_type_id.warehouse_id
        ]))

        transfer_suggestions = self._compute_transfer_suggestions(so, so_lines_data)

        return {
            'id': so.id, 'name': so.name,
            'partner_id': [so.partner_id.id, so.partner_id.name] if so.partner_id else False,
            'warehouse_id': [so.warehouse_id.id, so.warehouse_id.name] if so.warehouse_id else False,
            'commitment_date': so.commitment_date.strftime('%Y-%m-%d %H:%M:%S') if so.commitment_date else False,
            'date_order': so.date_order.strftime('%Y-%m-%d %H:%M:%S') if so.date_order else False,
            'amount_total': so.amount_total,
            'state': so.state,
            'delivery_status': so.delivery_status,
            'real_delivery_status': real_delivery_status,
            'stock_status': stock_status,
            'is_fully_ready': is_fully_ready,
            'packing_status': packing_status,
            'picking_warehouse_ids': picking_warehouse_ids,
            'pos': po_data,
            'flows': flows,
            'pickings': flat_pickings,
            'lines': so_lines_data,
            'packages': package_groups,
            'total_packages_count': total_packages_count,
            'misa_shipping_address': so.misa_shipping_address or '',
            'x_studio_htgh': so.x_studio_htgh or '',
            'x_studio_delivery_type': so.x_studio_delivery_type or '',
            'x_studio_misa_saler_code': so.x_studio_misa_saler_code or '',
            'tag_ids': [[t.id, t.name, t.color] for t in so.tag_ids] if so.tag_ids else [],
            'transfer_suggestions': transfer_suggestions,
            'is_returned_or_stopped': so_status_dict.get('is_returned_or_stopped', False),
            'picking_slip_printed': bool(so.x_picking_slip_printed),
            'has_new_unprinted_pickings': so_status_dict.get('has_new_unprinted_pickings', False),
        }
