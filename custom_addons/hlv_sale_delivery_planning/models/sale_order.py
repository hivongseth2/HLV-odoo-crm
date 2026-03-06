from odoo import models, fields, api
from dateutil.relativedelta import relativedelta

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def get_delivery_dashboard_data(self, search_query='', filter_warehouse_id='all', filter_delivery_status='all', filter_stock_status='all', filter_date_from='', filter_date_to='', limit=12, offset=0):
        """
        Fetch SOs and matching POs to display on the OWL dashboard.
        """
        # Bỏ qua giới hạn 6 tháng để tìm đầy đủ 10k đơn hàng
        domain = [
            ('state', 'in', ['sale', 'done'])
        ]
        
        if filter_delivery_status != 'all':
            domain += [('delivery_status', '=', filter_delivery_status)]
        else:
            domain += ['|', ('delivery_status', 'in', ['pending', 'partial', False]), ('delivery_status', '=', False)]
            
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
        
        # --- LỌC BỘ NHỚ THEO STATUS KHO & PHÂN TRANG KÉP ---
        # --- LỌC BỘ NHỚ THEO STATUS KHO & PHÂN TRANG KÉP ---
        matched_sale_ids = []
        
        if filter_stock_status == 'all':
            matched_sale_ids = sales.ids
        else:
            # Chỉ lấy các product/warehouses cần thiết cho 1 lượt cache để tính stock status
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
                        
            # Lọc trong bộ nhớ theo filter custom
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
                
                stock_status = 'ready'
                if has_pending:
                    if is_fully_ready:
                        stock_status = 'ready'
                    elif total_avail > 0:
                        stock_status = 'partial_ready'
                    else:
                        stock_status = 'out_of_stock'
                        
                if stock_status == filter_stock_status:
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

            stock_status = 'ready'
            if has_pending:
                if is_fully_ready:
                    stock_status = 'ready'
                elif total_avail > 0:
                    stock_status = 'partial_ready'
                else:
                    stock_status = 'out_of_stock'

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
            
            # Cấu trúc luồng Phiếu Kho: Phân Nhánh Chuỗi Flow cho UI (Cho Card X)
            all_so_pickings = so.picking_ids
            def get_next_transfers(p):
                # Filter out the return pickings from the downstream moves
                downstream = p.move_ids.move_dest_ids.picking_id
                if hasattr(p, 'return_ids'):
                    return downstream.filtered(lambda x: x not in p.return_ids)
                else:
                    return downstream.filtered(lambda x: not (hasattr(x, 'return_id') and x.return_id.id == p.id))
                
            next_picking_ids = set()
            for p in all_so_pickings:
                for np in get_next_transfers(p):
                    if np in all_so_pickings:
                        next_picking_ids.add(np.id)
                
                # Cập nhật next_picking_ids để không gom Phiếu Trả về nhánh Gốc (Root)
                if hasattr(p, 'return_ids'):
                    for rp in p.return_ids:
                        if rp in all_so_pickings:
                            next_picking_ids.add(rp.id)
                else:
                    # Nếu model không có return_ids, tìm ngược
                    for rp in all_so_pickings.filtered(lambda x: hasattr(x, 'return_id') and x.return_id.id == p.id):
                        next_picking_ids.add(rp.id)
                        
            root_pickings = all_so_pickings.filtered(lambda p: p.id not in next_picking_ids and not p.backorder_id)
            if not root_pickings and all_so_pickings:
                root_pickings = all_so_pickings.filtered(lambda p: not p.backorder_id)
                if not root_pickings:
                    root_pickings = all_so_pickings
                    
            def build_flat_flow(current_p, current_chain):
                videos = att_by_picking.get(current_p.id, [])
                p_data = {
                    'id': current_p.id,
                    'name': current_p.name,
                    'state': current_p.state,
                    'type_name': current_p.picking_type_id.name or '',
                    'code': current_p.picking_type_id.code or '', # Code indicates in/out/internal
                    'scheduled_date': current_p.scheduled_date.strftime('%Y-%m-%d') if current_p.scheduled_date else False,
                    'backorder_of': current_p.backorder_id.name if current_p.backorder_id else False,
                    'return_of_id': current_p.return_id.id if hasattr(current_p, 'return_id') and current_p.return_id else False,
                    'return_of': current_p.return_id.name if hasattr(current_p, 'return_id') and current_p.return_id else False,
                    'videos': videos,
                    'returns': [],
                    'backorders': []
                }
                
                # Phiếu Cắt Từ (Backorders) - Xếp dọc cùng với Phiếu Gốc
                backorders = all_so_pickings.filtered(lambda x: x.backorder_id == current_p)
                for bo in backorders:
                    if bo.id != current_p.id:
                        p_data['backorders'].append({
                            'id': bo.id,
                            'name': bo.name,
                            'state': bo.state,
                            'type_name': bo.picking_type_id.name or '',
                            'backorder_of': bo.backorder_id.name if bo.backorder_id else False,
                            'videos': att_by_picking.get(bo.id, [])
                        })
                
                # Nối tiếp vào chuỗi (Con thuộc Mẹ)
                return_ps = []
                if hasattr(current_p, 'return_ids'):
                    return_ps = current_p.return_ids.filtered(lambda x: x in all_so_pickings)
                else:
                    return_ps = all_so_pickings.filtered(lambda x: hasattr(x, 'return_id') and x.return_id.id == current_p.id)
                
                for rp in return_ps:
                    if rp.id != current_p.id:
                        p_data['returns'].append({
                            'id': rp.id,
                            'name': rp.name,
                            'state': rp.state,
                            'type_name': rp.picking_type_id.name or '',
                            'videos': att_by_picking.get(rp.id, [])
                        })
                        
                current_chain.append(p_data)
                
                # Điểm dừng và phân nhánh tới Step Xuất Kho tiếp theo qua Mũi Tên Ngang
                next_ps = get_next_transfers(current_p).filtered(lambda x: x in all_so_pickings)
                
                for np in next_ps:
                    if np.id != current_p.id and np.id not in [x['id'] for x in current_chain]:
                        build_flat_flow(np, current_chain)
                        
                return current_chain

            flows = []
            for root in root_pickings:
                flows.append(build_flat_flow(root, []))
                
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
            'total_count': total_count
        }
