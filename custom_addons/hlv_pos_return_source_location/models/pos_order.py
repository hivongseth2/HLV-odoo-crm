# -*- coding: utf-8 -*-
from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)

class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _create_order_picking(self):
        """
        Ghi đè để ép Odoo phải đưa hàng hoàn về đúng vị trí kệ ban đầu.
        Can thiệp ở cả cấp độ Picking và Move.
        """
        res = super(PosOrder, self)._create_order_picking()
        
        for order in self:
            # Chỉ xử lý nếu đơn có hàng trả (qty < 0)
            refund_lines = order.lines.filtered(lambda l: l.qty < 0)
            if not refund_lines:
                continue

            _logger.info("POS Return detected for Order %s. Processing locations...", order.name)
            
            for picking in order.picking_ids:
                if picking.state in ('done', 'cancel'):
                    continue

                # Biến để lưu vị trí kệ đích nếu tìm thấy (dùng cho trường hợp chỉ có 1 vị trí đích)
                final_dest_location = False

                for move in picking.move_ids:
                    # Tìm dòng POS line tương ứng
                    line = refund_lines.filtered(lambda l: l.product_id == move.product_id)
                    
                    if line and line[0].refunded_orderline_id:
                        orig_line = line[0].refunded_orderline_id
                        orig_order = orig_line.order_id
                        
                        # Tìm lại vị trí kệ chính xác (Vị trí mà trước đây đã xuất đi cho khách hàng)
                        orig_move_lines = orig_order.sudo().picking_ids.move_line_ids.filtered(
                            lambda ml: ml.product_id == orig_line.product_id 
                            and ml.location_dest_id.usage == 'customer'
                            and ml.quantity > 0
                        )
                        
                        if orig_move_lines:
                            target_loc = orig_move_lines[0].location_id
                            if target_loc:
                                _logger.info("POS Return: Found Original Shelf [%s] for Product [%s]", 
                                           target_loc.complete_name, move.product_id.name)
                                
                                # Gán vị trí đích cho từng Move và Move Line
                                move.sudo().write({'location_dest_id': target_loc.id})
                                if move.move_line_ids:
                                    move.move_line_ids.sudo().write({'location_dest_id': target_loc.id})
                                
                                final_dest_location = target_loc
                        else:
                            _logger.warning("POS Return: Could not find original outgoing move for %s in Order %s", 
                                          move.product_id.name, orig_order.name)
                
                # Nếu tìm thấy vị trí đích và tất cả các move đều nên về đó, cập nhật luôn Picking Header
                if final_dest_location:
                    picking.sudo().write({'location_dest_id': final_dest_location.id})
                    _logger.info("POS Return: Updated Picking [%s] Header destination to [%s]", 
                               picking.name, final_dest_location.complete_name)
        return res
