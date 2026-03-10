# -*- coding: utf-8 -*-
from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _prepare_stock_move_vals(self, first_line, order_lines):
        """
        Odoo 18 hook: Chuan bi gia tri cho Stock Move tu POS Line.
        Neu la hang tra ve, tim ke goc de gan vao location_dest_id.
        """
        res = super()._prepare_stock_move_vals(first_line, order_lines)
        
        # first_line la pos.order.line
        if first_line.qty < 0 and first_line.refunded_orderline_id:
            try:
                orig_line = first_line.refunded_orderline_id
                orig_order = orig_line.order_id
                
                # Tìm lại vị trí kệ chính xác (Vị trí mà trước đây đã xuất đi cho khách hàng)
                all_ml = orig_order.sudo().picking_ids.move_line_ids.filtered(
                    lambda ml: ml.product_id == first_line.product_id and ml.quantity > 0
                )
                
                # Ưu tiên lấy dòng di chuyển đến Customer
                orig_move_lines = all_ml.filtered(lambda ml: ml.location_dest_id.usage == 'customer')
                if not orig_move_lines:
                    orig_move_lines = all_ml
                
                if orig_move_lines:
                    # Sắp xếp để lấy cái kệ chi tiết nhất (độ sâu của path cao nhất)
                    target_ml = sorted(orig_move_lines, key=lambda x: len(x.location_id.complete_name.split('/')), reverse=True)[0]
                    target_loc = target_ml.location_id
                    
                    if target_loc:
                        _logger.info("[HLV POS FIX] Found Original Shelf [%s] for Product [%s] in Refund Order [%s]", 
                                   target_loc.complete_name, first_line.product_id.name, first_line.order_id.name)
                        res['location_dest_id'] = target_loc.id
            except Exception as e:
                _logger.error("[HLV POS FIX] Error finding original shelf: %s", str(e))
                
        return res
