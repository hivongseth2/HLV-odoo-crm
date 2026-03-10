# -*- coding: utf-8 -*-
from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)

class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _prepare_order_line_move_vals(self, line, picking):
        """
        Can thiệp ngay từ lúc chuẩn bị dữ liệu cho Stock Move.
        Nếu là hàng trả về, tìm kệ gốc để gán vào location_dest_id.
        """
        res = super()._prepare_order_line_move_vals(line, picking)
        
        if line.qty < 0 and line.refunded_orderline_id:
            try:
                orig_line = line.refunded_orderline_id
                orig_order = orig_line.order_id
                
                # Tìm lại vị trí kệ chính xác (usage == 'customer' là điểm cuối cùng của đơn bán)
                orig_move_lines = orig_order.sudo().picking_ids.move_line_ids.filtered(
                    lambda ml: ml.product_id == orig_line.product_id 
                    and ml.location_dest_id.usage == 'customer'
                    and ml.quantity > 0
                )
                
                if orig_move_lines:
                    target_loc = orig_move_lines[0].location_id
                    if target_loc:
                        _logger.info("POS Return PREPARE: Found Original Shelf [%s] for %s", 
                                   target_loc.complete_name, line.product_id.name)
                        res['location_dest_id'] = target_loc.id
                else:
                    _logger.warning("POS Return PREPARE: No original move found for %s", line.product_id.name)
            except Exception as e:
                _logger.error("POS Return PREPARE error: %s", str(e))
                
        return res

    def _create_order_picking(self):
        """
        Vẫn giữ override này để Log xem Odoo tạo ra cái gì.
        """
        _logger.info("DEBUG: Entering _create_order_picking for Order: %s", self.name if len(self)==1 else "Multiple")
        res = super(PosOrder, self)._create_order_picking()
        
        for order in self:
            _logger.info("DEBUG: Pickings for %s: %s (States: %s)", 
                        order.name, order.picking_ids.mapped('name'), order.picking_ids.mapped('state'))
            
            for picking in order.picking_ids:
                _logger.info("DEBUG: Picking %s Dest: %s", picking.name, picking.location_dest_id.complete_name)
                for move in picking.move_ids:
                    _logger.info("DEBUG: Move %s Dest: %s", move.product_id.name, move.location_dest_id.complete_name)

        return res
