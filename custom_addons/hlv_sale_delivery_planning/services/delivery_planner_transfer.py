from odoo import models


class DeliveryPlannerServiceTransfer(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    def prepare_transfer_modal_data(self, sale_order_ids):
        """
        Chuẩn bị dữ liệu cho modal tạo phiếu luân chuyển.
        Tính các sản phẩm thiếu hàng theo đơn bán đã chọn,
        group theo kho nguồn (source_warehouse → product).
        Trả về:
          {
            warehouses: [{
              warehouse_id, warehouse_name, warehouse_code,
              lot_stock_id, lot_stock_name,
              picking_type_id, picking_type_name,
              transit_location_id, transit_location_name,
              default_partner_id, default_partner_name,
              products: [{product_id, product_name, product_code,
                          total_qty, order_names, available_at_source}],
            }],
            all_partners: [{id, name}],
          }
        """
        sale_orders = self.env['sale.order'].browse(sale_order_ids).exists()
        if not sale_orders:
            return {'warehouses': [], 'all_partners': []}

        # { from_wh_id: { prod_id: {...} } }
        wh_product_map = {}

        for so in sale_orders:
            if not so.warehouse_id:
                continue
            dest_wh_id = so.warehouse_id.id

            for line in so.order_line:
                if line.display_type or not line.product_id:
                    continue
                if line.product_id.type == 'service':
                    continue

                pending = max(line.product_uom_qty - line.qty_delivered, 0.0)
                if pending <= 0:
                    continue

                # Tồn kho khả dụng tại kho đích (kho của đơn bán)
                quants_dest = self.env['stock.quant'].sudo().search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', 'child_of', so.warehouse_id.lot_stock_id.id),
                ])
                free_dest = sum(
                    max(float(q.quantity) - float(q.reserved_quantity), 0.0)
                    for q in quants_dest
                )
                # Đã giữ cho dòng này
                reserved = sum(
                    line.move_ids.filtered(
                        lambda m: m.state not in ('cancel', 'done')
                    ).mapped('quantity')
                )
                effective = free_dest + reserved
                shortage = pending - effective
                if shortage <= 0:
                    continue

                # Tìm kho nguồn có hàng
                remaining = shortage
                other_warehouses = self.env['stock.warehouse'].search([('id', '!=', dest_wh_id)])
                for wh in other_warehouses:
                    if remaining <= 0:
                        break
                    quants = self.env['stock.quant'].sudo().search([
                        ('product_id', '=', line.product_id.id),
                        ('location_id', 'child_of', wh.lot_stock_id.id),
                    ])
                    available = sum(
                        max(float(q.quantity) - float(q.reserved_quantity), 0.0)
                        for q in quants
                    )
                    if available <= 0:
                        continue

                    suggest_qty = min(available, remaining)
                    remaining -= suggest_qty

                    from_wh_id = wh.id
                    prod_id = line.product_id.id

                    if from_wh_id not in wh_product_map:
                        wh_product_map[from_wh_id] = {}
                    if prod_id not in wh_product_map[from_wh_id]:
                        wh_product_map[from_wh_id][prod_id] = {
                            'product_id': prod_id,
                            'product_name': line.product_id.display_name,
                            'product_code': line.product_id.default_code or '',
                            'total_qty': 0.0,
                            'order_names': [],
                            'available_at_source': available,
                        }
                    wh_product_map[from_wh_id][prod_id]['total_qty'] += suggest_qty
                    if so.name not in wh_product_map[from_wh_id][prod_id]['order_names']:
                        wh_product_map[from_wh_id][prod_id]['order_names'].append(so.name)

        if not wh_product_map:
            return {'warehouses': [], 'all_partners': []}

        # Tìm vị trí luân chuyển (transit location)
        transit_location = self.env['stock.location'].search([
            ('usage', '=', 'transit'),
            ('active', '=', True),
        ], limit=1)
        if not transit_location:
            transit_location = self.env['stock.location'].search([
                ('complete_name', 'ilike', 'transit'),
                ('active', '=', True),
            ], limit=1)
        transit_location_id = transit_location.id if transit_location else False
        transit_location_name = transit_location.complete_name if transit_location else 'Inter-warehouse transit'

        warehouses_data = []
        for from_wh_id, products_map in wh_product_map.items():
            wh = self.env['stock.warehouse'].browse(from_wh_id)
            if not wh.exists():
                continue

            # Ưu tiên "Lệnh chuyển hàng nội bộ" — tránh chọn "Lưu kho"
            picking_type = self.env['stock.picking.type'].search([
                ('warehouse_id', '=', from_wh_id),
                ('code', '=', 'internal'),
                ('name', 'ilike', 'nội bộ'),
            ], limit=1)
            if not picking_type:
                picking_type = self.env['stock.picking.type'].search([
                    ('warehouse_id', '=', from_wh_id),
                    ('code', '=', 'internal'),
                    ('name', 'ilike', 'chuyển'),
                ], limit=1)
            if not picking_type:
                # Fallback: internal nhưng loại trừ "lưu kho" và "nhập kho"
                picking_type = self.env['stock.picking.type'].search([
                    ('warehouse_id', '=', from_wh_id),
                    ('code', '=', 'internal'),
                    ('name', 'not ilike', 'lưu'),
                    ('name', 'not ilike', 'nhập'),
                ], limit=1)

            default_partner = wh.partner_id if wh.partner_id else False

            products_list = sorted(
                products_map.values(),
                key=lambda x: x['product_code'] or x['product_name'],
            )

            warehouses_data.append({
                'warehouse_id': from_wh_id,
                'warehouse_name': wh.name,
                'warehouse_code': wh.code or '',
                'lot_stock_id': wh.lot_stock_id.id if wh.lot_stock_id else False,
                'lot_stock_name': wh.lot_stock_id.complete_name if wh.lot_stock_id else '',
                'picking_type_id': picking_type.id if picking_type else False,
                'picking_type_name': picking_type.name if picking_type else f'Lệnh chuyển hàng nội bộ từ {wh.name}',
                'transit_location_id': transit_location_id,
                'transit_location_name': transit_location_name,
                # Partner áp dụng cứng từ địa chỉ kho, không cần người dùng chọn
                'partner_id': default_partner.id if default_partner else False,
                'partner_name': default_partner.name if default_partner else '',
                'products': products_list,
            })

        return {
            'warehouses': warehouses_data,
        }

    def create_transfer_pickings(self, warehouse_selections):
        """
        Tạo phiếu luân chuyển nội bộ từ dữ liệu đã xác nhận.

        warehouse_selections: list of {
            warehouse_id: int,
            picking_type_id: int,
            lot_stock_id: int,
            transit_location_id: int,
            partner_id: int or False,
            products: [{ product_id: int, total_qty: float }],
        }

        Returns: { created: [{ picking_id, picking_name, warehouse_name }], errors: [] }
        """
        created = []
        errors = []

        for sel in warehouse_selections:
            try:
                wh = self.env['stock.warehouse'].browse(sel['warehouse_id'])
                picking_type = self.env['stock.picking.type'].browse(
                    sel.get('picking_type_id') or 0
                )
                if not picking_type.exists():
                    picking_type = None

                location_id = sel.get('lot_stock_id') or (wh.lot_stock_id.id if wh.lot_stock_id else False)
                location_dest_id = sel.get('transit_location_id')

                if not location_dest_id:
                    transit = self.env['stock.location'].search(
                        [('usage', '=', 'transit'), ('active', '=', True)], limit=1
                    )
                    location_dest_id = transit.id if transit else False

                partner_id = sel.get('partner_id') or False

                move_vals = []
                for p in sel.get('products', []):
                    if not p.get('product_id') or not p.get('total_qty', 0):
                        continue
                    prod = self.env['product.product'].browse(p['product_id'])
                    move_vals.append((0, 0, {
                        'product_id': prod.id,
                        'name': prod.display_name,
                        'product_uom_qty': p['total_qty'],
                        'product_uom': prod.uom_id.id,
                        'location_id': location_id,
                        'location_dest_id': location_dest_id,
                    }))

                if not move_vals:
                    continue

                picking_vals = {
                    'location_id': location_id,
                    'location_dest_id': location_dest_id,
                    'partner_id': partner_id,
                    'origin': f'HLV luân chuyển từ {wh.name}',
                    'move_ids': move_vals,
                }
                if picking_type:
                    picking_vals['picking_type_id'] = picking_type.id

                picking = self.env['stock.picking'].create(picking_vals)

                created.append({
                    'picking_id': picking.id,
                    'picking_name': picking.name,
                    'warehouse_name': wh.name,
                })
            except Exception as exc:
                errors.append({
                    'warehouse_id': sel.get('warehouse_id'),
                    'error': str(exc),
                })

        return {'created': created, 'errors': errors}

    def prepare_relocation_data(self, sale_order_ids):
        """
        Chuẩn bị dữ liệu cho modal "Chuyển vị trí".
        Chỉ lấy sản phẩm đã được assign (có tồn kho đã giữ) từ các phiếu active.
        Trả về:
          {
            orders: [{
              sale_order_id, sale_order_name, warehouse_id, warehouse_name,
              products: [{product_id, product_name, product_code, pending_qty}]
            }],
            dest_locations: [{id, name}],
            default_dest_location_id: int or False,
          }
        """
        sale_orders = self.env['sale.order'].browse(sale_order_ids).exists()
        if not sale_orders:
            return {'orders': [], 'dest_locations': [], 'default_dest_location_id': False}

        # Lấy cấu hình vị trí đích mặc định (nếu có)
        default_dest_id = int(
            self.env['ir.config_parameter'].sudo().get_param(
                'hlv_delivery_planning.relocation_dest_location_id', '0'
            )
        ) or False

        orders_data = []
        all_warehouse_ids = set()

        for so in sale_orders:
            if not so.warehouse_id:
                continue
            all_warehouse_ids.add(so.warehouse_id.id)

            # Lấy các phiếu active (chưa done/cancel, không phải trả hàng)
            active_pickings = so.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel')
                and p.picking_type_code in ('outgoing', 'internal')
                and not p.return_id
            )

            # Gom số lượng đã assign (reserved) theo sản phẩm từ các move đã giữ hàng
            products = {}
            for pick in active_pickings:
                for move in pick.move_ids:
                    if move.state not in ('assigned', 'partially_available'):
                        continue
                    # Số lượng đã giữ = tổng qty trên move_line_ids
                    reserved = sum(ml.quantity for ml in move.move_line_ids)
                    if reserved <= 0:
                        continue
                    pid = move.product_id.id
                    if pid in products:
                        products[pid]['pending_qty'] += reserved
                    else:
                        products[pid] = {
                            'product_id': pid,
                            'product_name': move.product_id.display_name,
                            'product_code': move.product_id.default_code or '',
                            'pending_qty': reserved,
                        }

            product_list = sorted(products.values(), key=lambda p: p['product_code'] or p['product_name'])
            if product_list:
                orders_data.append({
                    'sale_order_id': so.id,
                    'sale_order_name': so.name,
                    'warehouse_id': so.warehouse_id.id,
                    'warehouse_name': so.warehouse_id.name,
                    'products': product_list,
                })

        # Lấy danh sách vị trí con (internal) của các kho liên quan
        dest_locations = []
        if all_warehouse_ids:
            warehouse_locs = self.env['stock.warehouse'].browse(list(all_warehouse_ids)).mapped('lot_stock_id')
            locations = self.env['stock.location'].search([
                ('location_id', 'child_of', warehouse_locs.ids),
                ('usage', '=', 'internal'),
            ], order='complete_name')
            dest_locations = [{'id': loc.id, 'name': loc.complete_name} for loc in locations]

        return {
            'orders': orders_data,
            'dest_locations': dest_locations,
            'default_dest_location_id': default_dest_id,
        }

    def create_relocation_pickings(self, relocation_data):
        """
        Tạo phiếu chuyển vị trí nội bộ (1 phiếu / đơn hàng).

        relocation_data: {
            dest_location_id: int,
            save_as_default: bool,
            orders: [{ sale_order_id: int, products: [{ product_id: int, qty: float }] }],
        }

        Returns: { created: [{ picking_id, picking_name, sale_order_name }], errors: [] }
        """
        created = []
        errors = []

        dest_location_id = relocation_data.get('dest_location_id')
        if not dest_location_id:
            return {'created': [], 'errors': [{'error': 'Chưa chọn vị trí đích'}]}

        # Lưu vị trí đích mặc định nếu user muốn
        if relocation_data.get('save_as_default'):
            self.env['ir.config_parameter'].sudo().set_param(
                'hlv_delivery_planning.relocation_dest_location_id',
                str(dest_location_id),
            )

        for order_data in relocation_data.get('orders', []):
            try:
                so = self.env['sale.order'].browse(order_data['sale_order_id'])
                if not so.exists() or not so.warehouse_id:
                    continue

                # Tìm picking type "Lệnh chuyển hàng nội bộ" của kho
                wh = so.warehouse_id
                picking_type = self.env['stock.picking.type'].search([
                    ('warehouse_id', '=', wh.id),
                    ('code', '=', 'internal'),
                    ('name', 'ilike', 'nội bộ'),
                ], limit=1)
                if not picking_type:
                    picking_type = self.env['stock.picking.type'].search([
                        ('warehouse_id', '=', wh.id),
                        ('code', '=', 'internal'),
                        ('name', 'not ilike', 'lưu'),
                        ('name', 'not ilike', 'nhập'),
                    ], limit=1)

                source_location_id = wh.lot_stock_id.id

                move_vals = []
                for p in order_data.get('products', []):
                    if not p.get('product_id') or not p.get('qty', 0):
                        continue
                    prod = self.env['product.product'].browse(p['product_id'])
                    move_vals.append((0, 0, {
                        'product_id': prod.id,
                        'name': prod.display_name,
                        'product_uom_qty': p['qty'],
                        'product_uom': prod.uom_id.id,
                        'location_id': source_location_id,
                        'location_dest_id': dest_location_id,
                    }))

                if not move_vals:
                    continue

                picking_vals = {
                    'picking_type_id': picking_type.id if picking_type else False,
                    'location_id': source_location_id,
                    'location_dest_id': dest_location_id,
                    'origin': f'{so.name} - Chuyển vị trí',
                    'move_ids': move_vals,
                }

                picking = self.env['stock.picking'].create(picking_vals)
                # Giữ hàng (reserve) cho phiếu vừa tạo — tương tự luồng in phiếu
                picking.action_assign()
                created.append({
                    'picking_id': picking.id,
                    'picking_name': picking.name,
                    'sale_order_name': so.name,
                })
            except Exception as exc:
                errors.append({
                    'sale_order_id': order_data.get('sale_order_id'),
                    'error': str(exc),
                })

        return {'created': created, 'errors': errors}
