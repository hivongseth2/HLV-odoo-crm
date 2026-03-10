from odoo import models


class DeliveryPlannerServiceFormatter(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

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

        # --- Dòng sản phẩm ---
        has_pending = False
        has_delivered = False
        is_fully_ready = True
        so_lines_data = []

        for line in so.order_line:
            if line.display_type:
                continue

            p_name = line.product_id.display_name if line.product_id else 'Unknown'
            p_type = line.product_id.type if line.product_id else 'service'
            is_kit = line.product_id.product_tmpl_id.id in kit_tmpl_ids

            base_free = (
                product_availabilities.get((line.product_id.id, so.warehouse_id.id), 0.0)
                if line.product_id and so.warehouse_id else 0.0
            )
            reserved_here = sum(
                line.move_ids.filtered(lambda m: m.state not in ('cancel', 'done')).mapped('quantity')
            )
            qty_avail = base_free + reserved_here
            qty_packed = qty_packed_map.get(p_name, 0.0)

            so_lines_data.append({
                'id': line.id,
                'product_id': [line.product_id.id, p_name] if line.product_id else False,
                'product_uom_qty': line.product_uom_qty,
                'qty_delivered': line.qty_delivered,
                'qty_packed': qty_packed,
                'qty_available': qty_avail,
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
                'videos': att_by_picking.get(p.id, []),
            })

        flows = self._build_flow_nodes(so, att_by_picking)
        picking_warehouse_ids = list(set([
            p.picking_type_id.warehouse_id.id
            for p in so.picking_ids
            if p.picking_type_id and p.picking_type_id.warehouse_id
        ]))

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
        }
