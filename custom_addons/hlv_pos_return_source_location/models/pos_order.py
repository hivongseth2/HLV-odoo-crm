# -*- coding: utf-8 -*-
from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)

class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    def _prepare_stock_move_vals(self, picking, location_id, location_dest_id):
        """
        Ghi đè để gán vị trí đích của hàng trả về (refund) 
        là vị trí nguồn (source) ban đầu của sản phẩm.
        """
        vals = super()._prepare_stock_move_vals(picking, location_id, location_dest_id)
        
        # Nếu là dòng hoàn tiền (qty < 0) và có liên kết với dòng gốc
        if self.qty < 0 and self.refunded_orderline_id:
            try:
                original_line = self.refunded_orderline_id
                original_order = original_line.order_id
                
                # Tìm các dịch chuyển kho (stock move) của đơn hàng gốc cho sản phẩm này
                # Ưu tiên lấy move đã hoàn thành (done)
                original_moves = original_order.picking_ids.move_ids.filtered(
                    lambda m: m.product_id == original_line.product_id and m.state == 'done'
                )
                
                if original_moves:
                    # Lấy vị trí nguồn ban đầu của sản phẩm
                    original_source_location = original_moves[0].location_id
                    if original_source_location:
                        _logger.info("POS Return: Redirecting product %s back to original source %s", 
                                   self.product_id.name, original_source_location.name)
                        vals['location_dest_id'] = original_source_location.id
            except Exception as e:
                _logger.error("POS Return Error: Could not determine original source location: %s", str(e))
                    
        return vals
