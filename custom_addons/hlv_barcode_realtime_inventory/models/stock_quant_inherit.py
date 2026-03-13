# -*- coding: utf-8 -*-
from odoo import models, api
from collections import defaultdict


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    @api.model
    def apply_realtime_inventory_sessions(self, location_id=None):
        """
        Merge tất cả active sessions vào stock.quant (inventory adjustment).
        Được gọi khi user nhấn "Xác nhận" trên barcode UI.
        """
        Session = self.env['inventory.scan.session']
        
        domain = [('state', '=', 'active')]
        if location_id:
            domain.append(('location_id', '=', location_id))
        
        sessions = Session.sudo().search(domain)
        
        if not sessions:
            return {'merged': 0, 'message': 'Không có session nào để merge'}
        
        # Tổng hợp theo (product_id, location_id, lot_id)
        summary = defaultdict(float)
        
        for session in sessions:
            for line in session.line_ids:
                key = (
                    line.product_id.id,
                    line.location_id.id if line.location_id else session.location_id.id,
                    line.lot_id.id if line.lot_id else False
                )
                summary[key] += line.quantity
        
        # Apply vào stock.quant
        updated_count = 0
        for (product_id, loc_id, lot_id), qty in summary.items():
            quant = self.sudo().search([
                ('product_id', '=', product_id),
                ('location_id', '=', loc_id),
                ('lot_id', '=', lot_id) if lot_id else ('lot_id', '=', False),
            ], limit=1)
            
            if quant:
                # Update existing quant
                quant.sudo().write({'inventory_quantity': qty})
                quant.sudo().action_apply_inventory()
            else:
                # Create new quant with inventory
                self.sudo().create({
                    'product_id': product_id,
                    'location_id': loc_id,
                    'lot_id': lot_id,
                    'inventory_quantity': qty,
                })
            updated_count += 1
        
        # Đánh dấu sessions là confirmed
        sessions.sudo().write({
            'state': 'confirmed',
            'confirmed_time': self.env.cr.now()
        })
        
        return {
            'merged': len(sessions),
            'quants_updated': updated_count,
            'message': f'Đã merge {len(sessions)} sessions, cập nhật {updated_count} quants'
        }
