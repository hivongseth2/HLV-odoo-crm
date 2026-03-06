from odoo import models, fields, api
from dateutil.relativedelta import relativedelta

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def get_delivery_dashboard_data(self):
        """
        Fetch SOs and matching POs to display on the OWL dashboard.
        """
        # Tránh bỏ sót đơn hàng (Đặc biệt đơn cũ trên 6 tháng hoặc đơn gãy logic status)
        six_months_ago = fields.Datetime.now() - relativedelta(months=6)
        domain = [
            ('state', 'in', ['sale', 'done']),
            '|',
            ('delivery_status', 'in', ['pending', 'partial', False]),
            ('date_order', '>=', six_months_ago)
        ]
        
        # Add order to prioritize the ones with earlier commitment dates
        sales = self.search(domain, order='commitment_date asc, date_order desc')
        
        # --- BATCH QUERIES OPTIMIZATION ---
        # 1. Lấy tất cả POs cho list SO name
        sale_names = sales.mapped('name')
        all_pos = self.env['purchase.order'].search([('origin', 'in', sale_names)]) if sale_names else []
        po_by_origin = {}
        for po in all_pos:
            if po.origin not in po_by_origin:
                po_by_origin[po.origin] = []
            po_by_origin[po.origin].append(po)
            
        # 2. Lấy tất cả Video Attachment cho list Picking ID
        all_picking_ids = sales.mapped('picking_ids').ids
        att_by_picking = {}
        if all_picking_ids:
            attachments = self.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'stock.picking'),
                ('res_id', 'in', all_picking_ids)
            ])
            for att in attachments:
                if att.name and (att.name.lower().endswith(('.webm', '.mp4')) or 'video' in (att.mimetype or '')):
                    if att.res_id not in att_by_picking:
                        att_by_picking[att.res_id] = []
                    att_by_picking[att.res_id].append({
                        'id': att.id,
                        'name': att.name,
                        'url': f'/web/content/{att.id}?download=true'
                    })

        # --- PRE-COMPUTE QTY AVAILABLE ---
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

        result = []
        for so in sales:
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
                            if qty_avail < pending_qty:
                                is_fully_ready = False
                        
                        if line.qty_delivered > 0:
                            has_delivered = True

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
            
            # Gom nhóm Picking theo loại (Pick -> Pack -> Out)
            flat_pickings = []
            picking_groups = {}
            for p in so.picking_ids.sorted(key=lambda x: (x.picking_type_id.sequence, x.id)):
                # Lấy video từ file đính kèm (Sử dụng dict để tránh query N+1)
                videos = att_by_picking.get(p.id, [])

                p_data = {
                    'id': p.id,
                    'name': p.name,
                    'state': p.state,
                    'type_name': p.picking_type_id.name or '',
                    'code': p.picking_type_id.code or '',
                    'scheduled_date': p.scheduled_date.strftime('%Y-%m-%d') if p.scheduled_date else False,
                    'backorder_of': p.backorder_id.name if p.backorder_id else False,
                    'videos': videos,
                }
                flat_pickings.append(p_data)
                
                t_name = p_data['type_name'] or 'Unknown'
                if t_name not in picking_groups:
                    picking_groups[t_name] = []
                picking_groups[t_name].append(p_data)
                
            pickings_by_type = [{'type_name': k, 'pickings': v} for k, v in picking_groups.items()]
            
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
                'is_fully_ready': is_fully_ready,
                'picking_warehouse_ids': picking_warehouse_ids,
                'pos': po_data,
                'pickings': flat_pickings,
                'pickings_by_type': pickings_by_type,
                'lines': so_lines_data,
            })
            
        # Get active warehouses for filter
        warehouses = self.env['stock.warehouse'].search_read([], ['id', 'name'])
            
        return {
            'orders': result,
            'warehouses': warehouses
        }
