from odoo import models


class DeliveryPlannerServiceStock(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    def _calculate_po_and_stock_status(
        self, sales, po_date_from, po_date_to, po_status,
        filter_stock_status, filter_packing_status,
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
        for w_id, prod_ids in product_qty_cache.items():
            if prod_ids:
                prods = self.env['product.product'].browse(list(prod_ids)).with_context(warehouse=w_id)
                # Odoo 18: free_qty = qty_available - reserved_quantity
                for p in prods:
                    product_availabilities[(p.id, w_id)] = p.free_qty

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
        matched_sale_ids = []
        dashboard_stats = {
            'total': 0, 'ready': 0, 'partial': 0, 'out_of_stock': 0,
            'packing_fully': 0, 'packing_partial': 0,
            'packing_unpacked': 0, 'packing_waiting': 0,
        }
        so_status_dict = {}

        for so in sales:
            has_pending = False
            is_fully_ready = True
            total_pending, total_avail = 0, 0

            for line in so.order_line:
                if line.display_type or not line.product_id:
                    continue
                p_type = line.product_id.type
                is_kit = line.product_id.product_tmpl_id.id in kit_tmpl_ids
                if p_type == 'service' or is_kit:
                    continue

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

            packed_qty = packed_qty_by_so.get(so.id, 0.0)
            # "Đã đóng gói đủ" = đã đóng hết phần có thể đóng ngay tại thời điểm hiện tại.
            # Cụ thể: so sánh số đã đóng với tổng qty có thể xuất (total_avail = min(available, pending) từng line).
            # Đơn đã giao xong không xét vào kiểm soát đóng gói.
            if not has_pending:
                packing_status = 'delivered'
            elif total_avail <= 0:
                packing_status = 'waiting_stock'
            elif packed_qty >= total_avail:
                packing_status = 'fully_packed'
            else:
                # Còn phần có thể đóng nhưng chưa đóng hết.
                packing_status = 'unpacked'
            so_status_dict[so.id] = {
                'stock_status': stock_status,
                'packing_status': packing_status,
            }

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

            if (
                (filter_stock_status == 'all' or stock_status == filter_stock_status)
                and (filter_packing_status == 'all' or packing_status == filter_packing_status)
            ):
                matched_sale_ids.append(so.id)

        return sales, matched_sale_ids, dashboard_stats, product_availabilities, so_status_dict
