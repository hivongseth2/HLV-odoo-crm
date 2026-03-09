from odoo import models, fields, api
import re

class DeliveryPlannerService(models.AbstractModel):
    _name = 'hlv.delivery.planner.service'
    _description = 'Delivery Planner Dashboard Service'

    @api.model
    def get_dashboard_data(self, search_query='', filter_warehouse_id='all', filter_delivery_status='all', filter_stock_status='all', filter_packing_status='all', filter_date_from='', filter_date_to='', filter_po_date_from='', filter_po_date_to='', filter_po_status='all', limit=12, offset=0):
        domain = self._build_search_domain(search_query, filter_warehouse_id, filter_delivery_status, filter_date_from, filter_date_to)
        sales = self.env['sale.order'].search(domain, order='commitment_date asc, date_order desc')

        sales, matched_ids, dashboard_stats, product_availabilities, so_status_dict = self._calculate_po_and_stock_status(
            sales, filter_po_date_from, filter_po_date_to, filter_po_status, filter_stock_status, filter_packing_status
        )

        total_count = len(matched_ids)
        page_sales = self.env['sale.order'].browse(matched_ids[int(offset):int(offset) + int(limit)])

        po_by_origin = self._fetch_pos_for_sales(page_sales)
        att_by_picking = self._fetch_attachments_for_pickings(page_sales.mapped('picking_ids').ids)
        so_packages_dict = self._fetch_packages_for_sales(page_sales)
        
        result = [self._format_dashboard_order(so, po_by_origin, product_availabilities, att_by_picking, so_packages_dict, so_status_dict.get(so.id, {})) for so in page_sales]
        warehouses = self.env['stock.warehouse'].search_read([], ['id', 'name'])
            
        return {
            'orders': result,
            'warehouses': warehouses,
            'total_count': total_count,
            'dashboard_stats': dashboard_stats
        }

    def _build_search_domain(self, search_query, filter_warehouse_id, filter_delivery_status, filter_date_from, filter_date_to):
        domain = [('state', 'in', ['sale', 'done'])]
        if filter_delivery_status == 'pending_partial':
            domain += [('delivery_status', 'in', ['pending', 'partial'])]
        elif filter_delivery_status != 'all':
            domain += [('delivery_status', '=', filter_delivery_status)]
        if filter_warehouse_id != 'all':
            domain += [('warehouse_id', '=', int(filter_warehouse_id))]
        if search_query:
            domain += ['|', ('name', 'ilike', search_query), ('partner_id.name', 'ilike', search_query)]
        if filter_date_from:
            domain += ['|', ('commitment_date', '>=', filter_date_from), '&', ('commitment_date', '=', False), ('date_order', '>=', filter_date_from)]
        if filter_date_to:
            domain += ['|', ('commitment_date', '<=', filter_date_to), '&', ('commitment_date', '=', False), ('date_order', '<=', filter_date_to)]
        return domain

    def _calculate_po_and_stock_status(self, sales, po_date_from, po_date_to, po_status, filter_stock_status, filter_packing_status):
        if po_date_from or po_date_to or (po_status and po_status != 'all'):
            po_domain = [('origin', 'in', sales.mapped('name'))]
            if po_date_from: po_domain.append(('date_planned', '>=', po_date_from))
            if po_date_to: po_domain.append(('date_planned', '<=', po_date_to + ' 23:59:59'))
            if po_status and po_status != 'all': po_domain.append(('receipt_status', '=', po_status))
            
            matching_pos = self.env['purchase.order'].search_read(po_domain, ['origin'])
            origins = list(set([po['origin'] for po in matching_pos if po['origin']]))
            sales = sales.filtered(lambda s: s.name in origins)
            
        product_qty_cache = {}
        for so in sales:
            if so.warehouse_id:
                w_id = so.warehouse_id.id
                if w_id not in product_qty_cache: product_qty_cache[w_id] = set()
                for line in so.order_line:
                    if not line.display_type and line.product_id:
                        product_qty_cache[w_id].add(line.product_id.id)
                        
        product_availabilities = {}
        for w_id, prod_ids in product_qty_cache.items():
            if prod_ids:
                prods = self.env['product.product'].browse(list(prod_ids)).with_context(warehouse=w_id)
                for p in prods: product_availabilities[(p.id, w_id)] = p.qty_available

        all_picking_ids = sales.mapped('picking_ids').ids
        packed_qty_by_so = {}
        if all_picking_ids:
            packed_groups = self.env['stock.move.line']._read_group(
                [('picking_id', 'in', all_picking_ids), ('result_package_id', '!=', False), ('state', '!=', 'cancel')],
                ['picking_id'],
                ['quantity:sum']
            )
            for picking, qty in packed_groups:
                if picking.sale_id:
                    packed_qty_by_so[picking.sale_id.id] = packed_qty_by_so.get(picking.sale_id.id, 0) + float(qty)

        matched_sale_ids = []
        dashboard_stats = {
            'total': 0, 'ready': 0, 'partial': 0, 'out_of_stock': 0,
            'packing_fully': 0, 'packing_partial': 0, 'packing_unpacked': 0, 'packing_waiting': 0
        }
        so_status_dict = {}
        
        for so in sales:
            has_pending = False
            is_fully_ready = True
            total_pending, total_avail = 0, 0
            total_storable_qty = 0
            
            for line in so.order_line:
                if not line.display_type and line.product_id and line.product_id.type != 'service':
                    total_storable_qty += line.product_uom_qty
                    pending_qty = line.product_uom_qty - line.qty_delivered
                    if pending_qty > 0:
                        has_pending = True
                        total_pending += pending_qty
                        qty_avail = product_availabilities.get((line.product_id.id, so.warehouse_id.id), 0.0)
                        if qty_avail > 0: total_avail += min(qty_avail, pending_qty)
                        if qty_avail < pending_qty: is_fully_ready = False
                            
            if has_pending:
                stock_status = 'ready' if is_fully_ready else ('partial_ready' if total_avail > 0 else 'out_of_stock')
            else:
                stock_status = 'delivered'

            packed_qty = packed_qty_by_so.get(so.id, 0.0)
            if packed_qty >= total_storable_qty and total_storable_qty > 0:
                packing_status = 'fully_packed'
            elif packed_qty > 0:
                packing_status = 'partial_packed'
            else:
                if stock_status in ['ready', 'partial_ready']:
                    packing_status = 'unpacked'
                else:
                    packing_status = 'waiting_stock'

            so_status_dict[so.id] = {'stock_status': stock_status, 'packing_status': packing_status}
                
            dashboard_stats['total'] += 1
            if stock_status == 'ready': dashboard_stats['ready'] += 1
            elif stock_status == 'partial_ready': dashboard_stats['partial'] += 1
            elif stock_status == 'out_of_stock': dashboard_stats['out_of_stock'] += 1

            if packing_status == 'fully_packed': dashboard_stats['packing_fully'] += 1
            elif packing_status == 'partial_packed': dashboard_stats['packing_partial'] += 1
            elif packing_status == 'unpacked': dashboard_stats['packing_unpacked'] += 1
            elif packing_status == 'waiting_stock': dashboard_stats['packing_waiting'] += 1
                
            if (filter_stock_status == 'all' or stock_status == filter_stock_status) and \
               (filter_packing_status == 'all' or packing_status == filter_packing_status):
                matched_sale_ids.append(so.id)
                
        return sales, matched_sale_ids, dashboard_stats, product_availabilities, so_status_dict

    def _fetch_pos_for_sales(self, page_sales):
        sale_names = page_sales.mapped('name')
        all_pos = self.env['purchase.order'].search([('origin', 'in', sale_names)]) if sale_names else []
        po_by_origin = {}
        for po in all_pos:
            po_by_origin.setdefault(po.origin, []).append(po)
        return po_by_origin

    def _fetch_attachments_for_pickings(self, all_picking_ids):
        att_by_picking = {}
        if not all_picking_ids: return att_by_picking
            
        picking_attachments = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'stock.picking'), ('res_id', 'in', all_picking_ids)
        ])
        for att in picking_attachments:
            if att.name and (att.name.lower().endswith(('.webm', '.mp4')) or 'video' in (att.mimetype or '')):
                att_by_picking.setdefault(att.res_id, []).append({'id': att.id, 'name': att.name, 'url': f'/web/content/{att.id}?download=true'})
                
        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'stock.picking'), ('res_id', 'in', all_picking_ids)
        ])
        for msg in messages:
            if msg.attachment_ids:
                for att in msg.attachment_ids:
                    if att.name and (att.name.lower().endswith(('.webm', '.mp4')) or 'video' in (att.mimetype or '')):
                        if not any(a['url'] == f'/web/content/{att.id}?download=true' for a in att_by_picking.get(msg.res_id, [])):
                            att_by_picking.setdefault(msg.res_id, []).append({'id': att.id, 'name': att.name, 'url': f'/web/content/{att.id}?download=true'})
            if msg.body:
                if 'Video đóng gói' in msg.body or 'video' in msg.body.lower():
                    urls = re.findall(r'href=[\'"]([^\'"]+)[\'"]', msg.body)
                    for i, url in enumerate(urls):
                        clean_url = url.replace('&amp;', '&')
                        if not any(u['url'] == clean_url for u in att_by_picking.get(msg.res_id, [])):
                            att_by_picking.setdefault(msg.res_id, []).append({'id': f"log_{msg.id}_{i}", 'name': 'Video Đóng Gói', 'url': clean_url if not clean_url.startswith('http') else clean_url})
                else:
                    urls = re.findall(r'(\/web\/content\/[0-9]+.*?\.webm)', msg.body)
                    for i, url in enumerate(urls):
                        clean_url = url.replace('&amp;', '&')
                        if not any(u['url'] == clean_url for u in att_by_picking.get(msg.res_id, [])):
                            att_by_picking.setdefault(msg.res_id, []).append({'id': f"log_{msg.id}_{i}", 'name': 'Video Log', 'url': clean_url if not clean_url.startswith('http') else clean_url})
        return att_by_picking

    def _fetch_packages_for_sales(self, page_sales):
        all_picking_ids = page_sales.mapped('picking_ids').ids
        if not all_picking_ids: return {}
        
        move_lines = self.env['stock.move.line'].search_read([
            ('picking_id', 'in', all_picking_ids),
            ('result_package_id', '!=', False),
            ('state', '!=', 'cancel')
        ], ['picking_id', 'result_package_id', 'product_id', 'quantity'])

        if not move_lines: return {}

        package_ids = list(set([ml['result_package_id'][0] for ml in move_lines if ml['result_package_id']]))
        packages = self.env['stock.quant.package'].sudo().browse(package_ids)
        pack_dict = {}
        for p in packages:
            pack_dict[p.id] = {
                'id': p.id, 'name': p.name,
                'pack_sequence': getattr(p, 'pack_sequence', 0),
                'pack_total': getattr(p, 'pack_total', 0)
            }
        
        pack_contents = {}
        for ml in move_lines:
            pid = ml['result_package_id'][0]
            if pid not in pack_contents:
                pack_info = pack_dict.get(pid, {'id': pid, 'name': ml['result_package_id'][1], 'pack_sequence': 0, 'pack_total': 0})
                pack_contents[pid] = {
                    'id': pid,
                    'name': pack_info.get('name') or ml['result_package_id'][1],
                    'sequence': pack_info.get('pack_sequence') or 0,
                    'total': pack_info.get('pack_total') or 0,
                    'product_map': {}
                }
            prod_name = ml['product_id'][1] if ml['product_id'] else 'Unknown'
            qty = float(ml['quantity']) if ml.get('quantity') else 0.0
            pack_contents[pid]['product_map'][prod_name] = pack_contents[pid]['product_map'].get(prod_name, 0.0) + qty

        for pid, content in pack_contents.items():
            content['products_desc'] = " | ".join([f"{name} (x{int(qty) if qty.is_integer() else qty})" for name, qty in content['product_map'].items() if qty > 0])

        picking_to_so = {picking.id: so.id for so in page_sales for picking in so.picking_ids}
        packages_by_so = {}
        
        for ml in move_lines:
            so_id = picking_to_so.get(ml['picking_id'][0])
            if so_id:
                pid = ml['result_package_id'][0]
                if so_id not in packages_by_so:
                    packages_by_so[so_id] = {}
                packages_by_so[so_id][pid] = pack_contents[pid]

        final_so_packages = {}
        for so_id, p_dict in packages_by_so.items():
            final_so_packages[so_id] = sorted(list(p_dict.values()), key=lambda x: x['sequence'] or 0)
            
        return final_so_packages

    def _format_dashboard_order(self, so, po_by_origin, product_availabilities, att_by_picking, so_packages_dict, so_status_dict):
        pos = po_by_origin.get(so.name, [])
        po_data = []
        for po in pos:
            po_data.append({
                'id': po.id, 'name': po.name, 'state': po.state,
                'receipt_status': po.receipt_status if hasattr(po, 'receipt_status') else 'unknown',
                'date_planned': po.date_planned.strftime('%Y-%m-%d %H:%M:%S') if po.date_planned else False,
                'partner_id': [po.partner_id.id, po.partner_id.name] if po.partner_id else False,
                'amount_total': po.amount_total,
            })
            
        # Calculate packed quantity per product for this SO
        qty_packed_map = {} # {product_name: qty}
        for pack in so_packages_dict.get(so.id, []):
            for prod_name, qty in pack.get('product_map', {}).items():
                qty_packed_map[prod_name] = qty_packed_map.get(prod_name, 0.0) + qty

        has_pending = False
        has_delivered = False
        is_fully_ready = True
        so_lines_data = []
        for line in so.order_line:
            if not line.display_type:
                p_name = line.product_id.display_name if line.product_id else 'Unknown'
                p_type = line.product_id.type if line.product_id else 'service'
                qty_avail = product_availabilities.get((line.product_id.id, so.warehouse_id.id), 0.0) if line.product_id and so.warehouse_id else 0.0
                qty_packed = qty_packed_map.get(p_name, 0.0)
                
                so_lines_data.append({
                    'id': line.id,
                    'product_id': [line.product_id.id, p_name] if line.product_id else False,
                    'product_uom_qty': line.product_uom_qty, 
                    'qty_delivered': line.qty_delivered,
                    'qty_packed': qty_packed,
                    'qty_available': qty_avail, 
                    'product_type': p_type,
                })
                if p_type != 'service':
                    pending_qty = line.product_uom_qty - line.qty_delivered
                    if pending_qty > 0:
                        has_pending = True
                        if qty_avail < pending_qty: is_fully_ready = False
                    if line.qty_delivered > 0: has_delivered = True

        if has_pending:
            stock_status = 'ready' if is_fully_ready else ('partial_ready' if any(l['qty_available'] > 0 for l in so_lines_data if l['product_type'] != 'service') else 'out_of_stock')
        else:
            stock_status = 'delivered'

        # Lấy từ dictionary đã tính sẵn chứ không tính lại, an toàn và chuẩn xác
        packing_status = so_status_dict.get('packing_status', 'unknown')
        stock_status = so_status_dict.get('stock_status', stock_status)

        real_delivery_status = 'unknown'
        st = [l for l in so_lines_data if l.get('product_type') != 'service']
        if not st: real_delivery_status = 'full'
        elif has_pending and not has_delivered: real_delivery_status = 'unshipped'
        elif has_pending and has_delivered: real_delivery_status = 'partial'
        elif not has_pending and len(st) > 0: real_delivery_status = 'full'

        flat_pickings = []
        for p in sorted(so.picking_ids, key=lambda p: (p.date_done or p.scheduled_date or p.create_date, p.id)):
            flat_pickings.append({
                'id': p.id, 'name': p.name, 'state': p.state,
                'type_name': p.picking_type_id.name or '', 'code': p.picking_type_id.code or '',
                'scheduled_date': p.scheduled_date.strftime('%Y-%m-%d') if p.scheduled_date else False,
                'backorder_of': p.backorder_id.name if p.backorder_id else False,
                'return_of_id': p.return_id.id if p.return_id else False,
                'return_of': p.return_id.name if p.return_id else False,
                'videos': att_by_picking.get(p.id, []),
            })
            
        flows = self._build_flow_nodes(so, att_by_picking)
        picking_warehouse_ids = list(set([p.picking_type_id.warehouse_id.id for p in so.picking_ids if p.picking_type_id and p.picking_type_id.warehouse_id]))

        return {
            'id': so.id, 'name': so.name,
            'partner_id': [so.partner_id.id, so.partner_id.name] if so.partner_id else False,
            'warehouse_id': [so.warehouse_id.id, so.warehouse_id.name] if so.warehouse_id else False,
            'commitment_date': so.commitment_date.strftime('%Y-%m-%d %H:%M:%S') if so.commitment_date else False,
            'date_order': so.date_order.strftime('%Y-%m-%d %H:%M:%S') if so.date_order else False,
            'amount_total': so.amount_total, 'state': so.state,
            'delivery_status': so.delivery_status, 'real_delivery_status': real_delivery_status,
            'stock_status': stock_status, 'is_fully_ready': is_fully_ready,
            'packing_status': packing_status,
            'picking_warehouse_ids': picking_warehouse_ids,
            'pos': po_data, 'flows': flows, 'pickings': flat_pickings, 'lines': so_lines_data,
            'packages': so_packages_dict.get(so.id, []),
        }

    def _build_flow_nodes(self, so, att_by_picking):
        all_so_pickings = so.picking_ids
        return_ps_dict, stor_ps_dict, branch_ids = {}, {}, set()
        for p in all_so_pickings:
            if hasattr(p, 'return_ids') and p.return_ids:
                for rp in p.return_ids.filtered(lambda x: x in all_so_pickings):
                    return_ps_dict.setdefault(p.id, []).append(rp)
                    branch_ids.add(rp.id)
            else:
                for rp in all_so_pickings.filtered(lambda x: hasattr(x, 'return_id') and x.return_id.id == p.id):
                    return_ps_dict.setdefault(p.id, []).append(rp)
                    branch_ids.add(rp.id)
                    
        for rp_list in return_ps_dict.values():
            for rp in rp_list:
                for stor in rp.move_ids.move_dest_ids.picking_id.filtered(lambda x: x in all_so_pickings):
                    stor_ps_dict.setdefault(rp.id, []).append(stor)
                    branch_ids.add(stor.id)

        all_returns_and_stors, return_roots = set(), set()
        for rp_list in return_ps_dict.values():
            for rp in rp_list: return_roots.add(rp); all_returns_and_stors.add(rp)
        for stor_list in stor_ps_dict.values():
            for stor in stor_list: all_returns_and_stors.add(stor)

        main_roots = all_so_pickings.filtered(
            lambda x: x not in all_returns_and_stors and not any(m.picking_id in all_so_pickings and m.picking_id not in all_returns_and_stors and m.picking_id != x for m in x.move_ids.mapped('move_orig_ids'))
        )
        
        flows, path_counter = [], 1
        sorted_all_pickings = sorted(all_so_pickings.filtered(lambda p: p.state == 'done' and p.date_done), key=lambda p: p.date_done)
        sorted_pending = sorted(all_so_pickings.filtered(lambda p: p.state != 'done'), key=lambda p: p.scheduled_date or p.create_date)
        picking_seq_map = {p.id: idx + 1 for idx, p in enumerate(sorted_all_pickings + sorted_pending)}

        def build_path_nodes(path_pickings):
            return [{
                'id': p.id, 'name': p.name, 'state': p.state,
                'type_name': p.picking_type_id.name or '', 'code': p.picking_type_id.code or '',
                'global_seq': picking_seq_map.get(p.id, 0),
                'scheduled_date': p.scheduled_date.strftime('%Y-%m-%d') if p.scheduled_date else False,
                'backorder_of': p.backorder_id.name if p.backorder_id else False,
                'return_of': p.return_id.name if hasattr(p, 'return_id') and p.return_id else False,
                'videos': att_by_picking.get(p.id, [])
            } for p in path_pickings]

        def get_paths(picking, allowed_pickings):
            next_pickings = picking.move_ids.mapped('move_dest_ids.picking_id').filtered(lambda x: x in allowed_pickings and x.id != picking.id)
            if not next_pickings: return [[picking]]
            paths = []
            for np in next_pickings:
                for sub_path in get_paths(np, allowed_pickings):
                    if picking not in sub_path: paths.append([picking] + sub_path)
            return paths if paths else [[picking]]

        all_returns = self.env['stock.picking'].browse([p.id for p in all_returns_and_stors])
        outbound_allowed = all_so_pickings - all_returns
        for root in sorted(main_roots, key=lambda x: (x.scheduled_date or x.create_date, x.id)):
            for path in get_paths(root, outbound_allowed):
                flows.append({'id': f'path_{so.id}_{path_counter}', 'is_return': False, 'nodes': build_path_nodes(path)})
                path_counter += 1
                
        return_allowed = all_returns_and_stors
        for root in sorted(list(return_roots), key=lambda x: (x.scheduled_date or x.create_date, x.id)):
            for path in get_paths(root, return_allowed):
                flows.append({'id': f'path_{so.id}_{path_counter}', 'is_return': True, 'nodes': build_path_nodes(path)})
                path_counter += 1
            
        return flows
