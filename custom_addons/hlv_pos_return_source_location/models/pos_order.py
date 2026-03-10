# -*- coding: utf-8 -*-
from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)

class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    def _prepare_stock_move_vals(self, picking, location_id, location_dest_id):
        """
        Ghi đè để gán vị trí đích của hàng trả về (refund) 
        là vị trí nguồn (source) CHI TIẾT ban đầu của sản phẩm.
        """
        vals = super()._prepare_stock_move_vals(picking, location_id, location_dest_id)
        
        # Nếu là dòng hoàn tiền (qty < 0) và có liên kết với dòng gốc
        if self.qty < 0 and self.refunded_orderline_id:
            try:
                original_line = self.refunded_orderline_id
                original_order = original_line.order_id
                
                _logger.info("POS Return: Found refund line for product %s. Original Order: %s", 
                            self.product_id.name, original_order.name)

                # Tìm các dịch chuyển kho chi tiết (stock move line) của đơn hàng gốc
                # Move Line chứa vị trí chính xác (A1/T1) thay vì vị trí chung của Move
                original_move_lines = original_order.picking_ids.move_line_ids.filtered(
                    lambda ml: ml.product_id == original_line.product_id and ml.quantity > 0
                )
                
                if original_move_lines:
                    # Lấy vị trí nguồn (location_id) từ move line đầu công việc
                    # Chúng ta lấy move line của phiếu xuất (outgoing) ban đầu
                    # Trong phiếu xuất, location_id là kho, location_dest_id là khách hàng.
                    
                    # Lọc lấy move line từ phiếu xuất (picking type outgoing)
                    out_move_lines = original_move_lines.filtered(
                        lambda ml: ml.picking_id.picking_type_id.code == 'outgoing'
                    )
                    
                    target_ml = out_move_lines[0] if out_move_lines else original_move_lines[0]
                    original_source_location = target_ml.location_id
                    
                    if original_source_location:
                        _logger.info("POS Return: Redirecting to EXACT source location: %s (ID: %s)", 
                                   original_source_location.complete_name, original_source_location.id)
                        vals['location_dest_id'] = original_source_location.id
                else:
                    _logger.warning("POS Return: No original move lines found for product %s in order %s", 
                                   self.product_id.name, original_order.name)
            except Exception as e:
                _logger.error("POS Return Error: Could not determine original source location: %s", str(e))
                    
        return vals
