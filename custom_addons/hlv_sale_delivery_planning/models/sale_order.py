from odoo import models, fields, api
from dateutil.relativedelta import relativedelta

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def get_delivery_dashboard_data(self, search_query='', filter_warehouse_id='all', filter_delivery_status='all', filter_stock_status='all', filter_date_from='', filter_date_to='', filter_po_date_from='', filter_po_date_to='', filter_po_status='all', limit=12, offset=0):
        """
        Fetch SOs and matching POs to display on the OWL dashboard.
        """
        # Bỏ qua giới hạn 6 tháng để tìm đầy đủ 10k đơn hàng
        domain = [
            ('state', 'in', ['sale', 'done'])
        ]
        
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
        
        # Add order to prioritize the ones with earlier commitment dates
        sales = self.search(domain, order='commitment_date asc, date_order desc')
        
        # --- LỌC THEO NGÀY PO (MEMORY FILTER DỰA VÀO PURCHASE ORDER) ---
        if filter_po_date_from or filter_po_date_to or (filter_po_status and filter_po_status != 'all'):
            po_domain = [('origin', 'in', sales.mapped('name'))]
            if filter_po_date_from:
                po_domain.append(('date_planned', '>=', filter_po_date_from))
            if filter_po_date_to:
                po_domain.append(('date_planned', '<=', filter_po_date_to + ' 23:59:59'))
            if filter_po_status and filter_po_status != 'all':
                po_domain.append(('receipt_status', '=', filter_po_status))
            matching_pos = self.env['purchase.order'].search_read(po_domain, ['origin'])
            origins = list(set([po['origin'] for po in matching_pos if po['origin']]))
            sales = sales.filtered(lambda s: s.name in origins)
        
        # --- TÍNH TOÁN STOCK KHẢ DỤNG CHO TOÀN BỘ SALES ĐỂ LÀM DASHBOARD STATS ---
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
                for p in prods:
                    product_availabilities[(p.id, w_id)] = p.qty_available
                    
        # Lọc trong bộ nhớ theo filter custom & Tính KPI
        matched_sale_ids = []
        dashboard_stats = {'total': 0, 'ready': 0, 'partial': 0, 'out_of_stock': 0}
        
        for so in sales:
            has_pending = False
            is_fully_ready = True
            total_pending = 0
            total_avail = 0
            
            for line in so.order_line:
                if not line.display_type and line.product_id and line.product_id.type != 'service':
                    pending_qty = line.product_uom_qty - line.qty_delivered
                    if pending_qty > 0:
                        has_pending = True
                        total_pending += pending_qty
                        qty_avail = product_availabilities.get((line.product_id.id, so.warehouse_id.id), 0.0)
                        if qty_avail > 0:
                            total_avail += min(qty_avail, pending_qty)
                        if qty_avail < pending_qty:
                            is_fully_ready = False
            
            if has_pending:
                if is_fully_ready:
                    stock_status = 'ready'
                elif total_avail > 0:
                    stock_status = 'partial_ready'
                else:
                    stock_status = 'out_of_stock'
            else:
                stock_status = 'delivered'
                    
            # Tăng biến đếm Dashboard
            dashboard_stats['total'] += 1
            if stock_status == 'ready':
                dashboard_stats['ready'] += 1
            elif stock_status == 'partial_ready':
                dashboard_stats['partial'] += 1
            elif stock_status == 'out_of_stock':
                dashboard_stats['out_of_stock'] += 1
                    
            if filter_stock_status == 'all' or stock_status == filter_stock_status:
                matched_sale_ids.append(so.id)
                    
        total_count = len(matched_sale_ids)
        page_sale_ids = matched_sale_ids[int(offset):int(offset) + int(limit)]
        page_sales = self.env['sale.order'].browse(page_sale_ids)

        # --- BATCH QUERIES OPTIMIZATION CHỈ CHO TRANG HIỆN TẠI ---
        sale_names = page_sales.mapped('name')
        all_pos = self.env['purchase.order'].search([('origin', 'in', sale_names)]) if sale_names else []
        po_by_origin = {}
        for po in all_pos:
            if po.origin not in po_by_origin:
                po_by_origin[po.origin] = []
            po_by_origin[po.origin].append(po)
            
        # Lấy tất cả Video Attachment và Message cho list Picking ID của TRANG HIỆN TẠI
        all_picking_ids = page_sales.mapped('picking_ids').ids
        att_by_picking = {}
        if all_picking_ids:
            # 2.1. Tìm trong Attachments thông thường trực thuộc stock.picking
            picking_attachments = self.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'stock.picking'),
                ('res_id', 'in', all_picking_ids)
            ])
            for att in picking_attachments:
                if att.name and (att.name.lower().endswith(('.webm', '.mp4')) or 'video' in (att.mimetype or '')):
                    if att.res_id not in att_by_picking:
                        att_by_picking[att.res_id] = []
                    att_by_picking[att.res_id].append({
                        'id': att.id,
                        'name': att.name,
                        'url': f'/web/content/{att.id}?download=true'
                    })
                    
            # 2.2. Tìm trong Message Attachments (qua Chatter/Log note)
            messages = self.env['mail.message'].sudo().search([
                ('model', '=', 'stock.picking'),
                ('res_id', 'in', all_picking_ids)
            ])
            
            for msg in messages:
                # Tìm trong danh sách đính kèm của message
                if msg.attachment_ids:
                    for att in msg.attachment_ids:
                        if att.name and (att.name.lower().endswith(('.webm', '.mp4')) or 'video' in (att.mimetype or '')):
                            if msg.res_id not in att_by_picking:
                                att_by_picking[msg.res_id] = []
                            if not any(a['url'] == f'/web/content/{att.id}?download=true' for a in att_by_picking[msg.res_id]):
                                att_by_picking[msg.res_id].append({
                                    'id': att.id,
                                    'name': att.name,
                                    'url': f'/web/content/{att.id}?download=true'
                                })
                
                # Tìm file đính kèm trực tiếp nếu có .webm
                if msg.body:
                    import re
                    # Nếu có specific text
                    if 'Video đóng gói' in msg.body or 'video' in msg.body.lower():
                        urls = re.findall(r'href=[\'"]([^\'"]+)[\'"]', msg.body)
                        if urls:
                            if msg.res_id not in att_by_picking:
                                att_by_picking[msg.res_id] = []
                            for i, url in enumerate(urls):
                                clean_url = url.replace('&amp;', '&')
                                if not any(u['url'] == clean_url for u in att_by_picking[msg.res_id]):
                                    att_by_picking[msg.res_id].append({
                                        'id': f"log_{msg.id}_{i}",
                                        'name': 'Video Đóng Gói',
                                        'url': clean_url if not clean_url.startswith('http') else clean_url
                                    })
                    # Tìm dự phòng bằng Regex link .webm thẳng trong nội dung html
                    else:
                        urls = re.findall(r'(\/web\/content\/[0-9]+.*?\.webm)', msg.body)
                        if urls:
                            if msg.res_id not in att_by_picking:
                                att_by_picking[msg.res_id] = []
                            for i, url in enumerate(urls):
                                clean_url = url.replace('&amp;', '&')
                                if not any(u['url'] == clean_url for u in att_by_picking[msg.res_id]):
                                    att_by_picking[msg.res_id].append({
                                        'id': f"log_{msg.id}_{i}",
                                        'name': 'Video Log',
                                        'url': clean_url if not clean_url.startswith('http') else clean_url
                                    })

        # --- PRE-COMPUTE QTY AVAILABLE CHỈ CHO TRANG NÀY (TRỪ KHI ĐÃ CÓ FULL CACHE) ---
        if filter_stock_status == 'all':
            product_qty_cache = {}
            for so in page_sales:
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
                    for p in prods:
                        product_availabilities[(p.id, w_id)] = p.qty_available

        result = []
        for so in page_sales:
            # Lọc kho theo Phiếu Kho thay vì chỉ đơn thuần SO
            picking_warehouse_ids = list(set([p.picking_type_id.warehouse_id.id for p in so.picking_ids if p.picking_type_id and p.picking_type_id.warehouse_id]))

            # Find POs by origin (Sử dụng dict để tránh query N+1)
            pos = po_by_origin.get(so.name, [])
            
            po_data = []
            for po in pos:
                po_data.append({
                    'id': po.id,
                    'name': po.name,
                    'state': po.state, # draft, sent, to approve, purchase, done, cancel
                    'receipt_status': po.receipt_status if hasattr(po, 'receipt_status') else 'unknown',
                    'date_planned': po.date_planned.strftime('%Y-%m-%d %H:%M:%S') if po.date_planned else False,
                    'partner_id': [po.partner_id.id, po.partner_id.name] if po.partner_id else False,
                    'amount_total': po.amount_total,
                })
                
            # Tính lại delivery status chính xác nhất
            has_pending = False
            has_delivered = False
            is_fully_ready = True
            
            total_pending = 0
            total_avail = 0

            so_lines_data = []
            for line in so.order_line:
                if not line.display_type:
                    p_type = line.product_id.type if line.product_id else 'service'
                    qty_avail = product_availabilities.get((line.product_id.id, so.warehouse_id.id), 0.0) if line.product_id and so.warehouse_id else 0.0
                    
                    so_lines_data.append({
                        'id': line.id,
                        'product_id': [line.product_id.id, line.product_id.display_name] if line.product_id else False,
                        'product_uom_qty': line.product_uom_qty,
                        'qty_delivered': line.qty_delivered,
                        'qty_available': qty_avail,
                        'product_type': p_type,
                    })
                    
                    if p_type != 'service':
                        pending_qty = line.product_uom_qty - line.qty_delivered
                        if pending_qty > 0:
                            has_pending = True
                            total_pending += pending_qty
                            if qty_avail > 0:
                                total_avail += min(qty_avail, pending_qty)
                            if qty_avail < pending_qty:
                                is_fully_ready = False
                        
                        if line.qty_delivered > 0:
                            has_delivered = True

            if has_pending:
                if is_fully_ready:
                    stock_status = 'ready'
                elif total_avail > 0:
                    stock_status = 'partial_ready'
                else:
                    stock_status = 'out_of_stock'
            else:
                stock_status = 'delivered'

            real_delivery_status = 'unknown'
            st = [l for l in so_lines_data if l.get('product_type') != 'service']
            if not st:
                real_delivery_status = 'full'
            elif has_pending and not has_delivered:
                real_delivery_status = 'unshipped'
            elif has_pending and has_delivered:
                real_delivery_status = 'partial'
            elif not has_pending and len(st) > 0:
                real_delivery_status = 'full'
                
            # Mảng phẳng (Cho Side Drawer Timeline Y)
            flat_pickings = []
            sorted_pickings = sorted(so.picking_ids, key=lambda p: (p.date_done or p.scheduled_date or p.create_date, p.id))
            
            for p in sorted_pickings:
                videos = att_by_picking.get(p.id, [])
                p_data = {
                    'id': p.id,
                    'name': p.name,
                    'state': p.state,
                    'type_name': p.picking_type_id.name or '',
                    'code': p.picking_type_id.code or '',
                    'scheduled_date': p.scheduled_date.strftime('%Y-%m-%d') if p.scheduled_date else False,
                    'backorder_of': p.backorder_id.name if p.backorder_id else False,
                    'return_of_id': p.return_id.id if p.return_id else False,
                    'return_of': p.return_id.name if p.return_id else False,
                    'videos': videos,
                }
                flat_pickings.append(p_data)
            
            # Cấu trúc luồng Phiếu Kho: Phân Loại Tuyến Đường (Path-based Flow)
            all_so_pickings = so.picking_ids
            
            # --- 1. Lọc Return Pickings (Các phiếu Nhập từ khách)
            return_ps_dict = {}
            stor_ps_dict = {}
            branch_ids = set()
            for p in all_so_pickings:
                if hasattr(p, 'return_ids') and p.return_ids:
                    for rp in p.return_ids:
                        if rp in all_so_pickings:
                            return_ps_dict.setdefault(p.id, []).append(rp)
                            branch_ids.add(rp.id)
                else:
                    for rp in all_so_pickings.filtered(lambda x: hasattr(x, 'return_id') and x.return_id.id == p.id):
                        return_ps_dict.setdefault(p.id, []).append(rp)
                        branch_ids.add(rp.id)
                        
            # Càn quét STORs (Phiếu lưu kho nội bộ sau khi Nhập)
            for rp_list in return_ps_dict.values():
                for rp in rp_list:
                    stors = rp.move_ids.move_dest_ids.picking_id.filtered(lambda x: x in all_so_pickings)
                    for stor in stors:
                        stor_ps_dict.setdefault(rp.id, []).append(stor)
                        branch_ids.add(stor.id)

            all_returns_and_stors = set()
            return_roots = set()
            for rp_list in return_ps_dict.values():
                for rp in rp_list:
                    return_roots.add(rp)
                    all_returns_and_stors.add(rp)
            for stor_list in stor_ps_dict.values():
                for stor in stor_list:
                    all_returns_and_stors.add(stor)

            # --- 2. Tìm Roots của luồng Xuất (Main Delivery)
            # Root là những phiếu KHÔNG nhận hàng từ bất kỳ phiếu nào khác trong SO này (trừ Return)
            main_roots = all_so_pickings.filtered(
                lambda x: x not in all_returns_and_stors and \
                not any(m.picking_id in all_so_pickings and m.picking_id not in all_returns_and_stors and m.picking_id != x for m in x.move_ids.mapped('move_orig_ids'))
            )
            
            flows = []
            path_counter = 1
            
            # Tính số thứ tự Chronological cho từng thẻ kho
            sorted_all_pickings = sorted(all_so_pickings.filtered(lambda p: p.state == 'done' and p.date_done), key=lambda p: p.date_done)
            sorted_pending = sorted(all_so_pickings.filtered(lambda p: p.state != 'done'), key=lambda p: p.scheduled_date or p.create_date)
            picking_seq_map = {p.id: idx + 1 for idx, p in enumerate(sorted_all_pickings + sorted_pending)}

            def build_path_nodes(path_pickings):
                nodes = []
                for p in path_pickings:
                    nodes.append({
                        'id': p.id,
                        'name': p.name,
                        'state': p.state,
                        'type_name': p.picking_type_id.name or '',
                        'code': p.picking_type_id.code or '',
                        'global_seq': picking_seq_map.get(p.id, 0),
                        'scheduled_date': p.scheduled_date.strftime('%Y-%m-%d') if p.scheduled_date else False,
                        'backorder_of': p.backorder_id.name if p.backorder_id else False,
                        'return_of': p.return_id.name if hasattr(p, 'return_id') and p.return_id else False,
                        'videos': att_by_picking.get(p.id, [])
                    })
                return nodes

            def get_paths(picking, allowed_pickings):
                # Tìm các phiếu tiếp theo nhận hàng từ phiếu hiện tại
                next_pickings = picking.move_ids.mapped('move_dest_ids.picking_id').filtered(
                    lambda x: x in allowed_pickings and x.id != picking.id
                )
                if not next_pickings:
                    return [[picking]]
                
                paths = []
                for np in next_pickings:
                    # Chặn vòng lặp vô hạn
                    for sub_path in get_paths(np, allowed_pickings):
                        if picking not in sub_path:
                            paths.append([picking] + sub_path)
                
                if not paths:
                    return [[picking]]
                return paths

            # --- 3. Generate Paths từ Xuất Kho Roots
            # Ép all_returns_and_stors về dạng RecordSet để trừ
            all_returns = self.env['stock.picking'].browse([p.id for p in all_returns_and_stors])
            outbound_allowed = all_so_pickings - all_returns
            for root in sorted(main_roots, key=lambda x: (x.scheduled_date or x.create_date, x.id)):
                paths = get_paths(root, outbound_allowed)
                for path in paths:
                    flows.append({
                        'id': f'path_{so.id}_{path_counter}',
                        'is_return': False,
                        'nodes': build_path_nodes(path)
                    })
                    path_counter += 1
                    
            # --- 4. Generate Paths từ Trả Hàng Roots
            # Đối với Trả hàng, allowed là danh sách return và stors nội bộ liên quan
            return_allowed = all_returns_and_stors
            for root in sorted(list(return_roots), key=lambda x: (x.scheduled_date or x.create_date, x.id)):
                paths = get_paths(root, return_allowed)
                for path in paths:
                    flows.append({
                        'id': f'path_{so.id}_{path_counter}',
                        'is_return': True,
                        'nodes': build_path_nodes(path)
                    })
                    path_counter += 1
                
            result.append({
                'id': so.id,
                'name': so.name,
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
                'picking_warehouse_ids': picking_warehouse_ids,
                'pos': po_data,
                'flows': flows,
                'pickings': flat_pickings,
                'lines': so_lines_data,
            })
            
        # Get active warehouses for filter
        warehouses = self.env['stock.warehouse'].search_read([], ['id', 'name'])
            
        return {
            'orders': result,
            'warehouses': warehouses,
            'total_count': total_count,
            'dashboard_stats': dashboard_stats
        }
