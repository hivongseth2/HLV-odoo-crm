from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def get_delivery_dashboard_data(self):
        """
        Fetch SOs and matching POs to display on the OWL dashboard.
        """
        # Fetch Sales Orders that are 'sale' or 'done' but not fully delivered
        # Since 'delivery_status' is standard if 'sale_stock' is installed, we can use it.
        # Wait, let's use standard status to be safe. If delivery_status is not there, we can fallback.
        # But we added 'purchase_stock' which depends on 'sale_stock', so delivery_status is available.
        
        domain = [
            ('state', 'in', ['sale', 'done']),
            ('delivery_status', 'in', ['pending', 'partial', 'full'])
        ]
        
        # Add order to prioritize the ones with earlier commitment dates
        sales = self.search(domain, order='commitment_date asc, date_order desc')
        
        result = []
        for so in sales:
            # Find POs by origin
            pos = self.env['purchase.order'].search([('origin', '=', so.name)])
            
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
                
            so_lines_data = []
            for line in so.order_line:
                if not line.display_type:
                    so_lines_data.append({
                        'id': line.id,
                        'product_id': [line.product_id.id, line.product_id.display_name] if line.product_id else False,
                        'product_uom_qty': line.product_uom_qty,
                        'qty_delivered': line.qty_delivered,
                        'qty_available': line.product_id.with_context(warehouse=so.warehouse_id.id).qty_available if line.product_id and so.warehouse_id else 0.0,
                    })
                    
            # Check if all lines are delivered or have enough stock ready
            is_fully_ready = True
            for l in so_lines_data:
                pending_qty = l['product_uom_qty'] - l['qty_delivered']
                if pending_qty > 0 and l['qty_available'] < pending_qty:
                    is_fully_ready = False
                    break
            
            # Gom nhóm Picking theo loại (Pick -> Pack -> Out)
            flat_pickings = []
            picking_groups = {}
            for p in so.picking_ids.sorted(key=lambda x: (x.picking_type_id.sequence, x.id)):
                # Lấy video từ file đính kèm
                attachments = self.env['ir.attachment'].sudo().search([
                    ('res_model', '=', 'stock.picking'),
                    ('res_id', '=', p.id)
                ])
                videos = []
                for att in attachments:
                    if att.name and (att.name.lower().endswith(('.webm', '.mp4')) or 'video' in (att.mimetype or '')):
                        videos.append({
                            'id': att.id,
                            'name': att.name,
                            'url': f'/web/content/{att.id}?download=true'
                        })

                # Truy xuất liên kết
                dest_picks = [n for n in set(p.move_ids.mapped('move_dest_ids.picking_id.name')) if n]
                orig_picks = [n for n in set(p.move_ids.mapped('move_orig_ids.picking_id.name')) if n]
                return_of = [n for n in set(p.move_ids.mapped('origin_returned_move_id.picking_id.name')) if n]

                p_data = {
                    'id': p.id,
                    'name': p.name,
                    'state': p.state,
                    'type_name': p.picking_type_id.name or '',
                    'code': p.picking_type_id.code or '',
                    'scheduled_date': p.scheduled_date.strftime('%Y-%m-%d') if p.scheduled_date else False,
                    'dest_picks': dest_picks,
                    'orig_picks': orig_picks,
                    'return_of': return_of,
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
                'is_fully_ready': is_fully_ready,
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
