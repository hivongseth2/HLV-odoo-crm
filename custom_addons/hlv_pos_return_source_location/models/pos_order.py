# -*- coding: utf-8 -*-
from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)

class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _create_order_picking(self):
        """
        Sau khi Odoo tạo xong picking và moves, ta can thiệp để sửa vị trí đích (location_dest_id)
        của các move hoàn tiền về đúng kệ (shelf) ban đầu.
        """
        res = super(PosOrder, self)._create_order_picking()
        
        for order in self:
            # Chỉ xử lý nếu là đơn hoàn tiền (có dòng qty < 0)
            if any(line.qty < 0 for line in order.lines):
                _logger.info("POS Return: Processing refund locations for Order %s", order.name)
                
                for picking in order.picking_ids:
                    # Chúng ta chỉ xử lý các phiếu chưa hoàn thành để có thể sửa location_dest_id
                    if picking.state in ('done', 'cancel'):
                        continue
                        
                    for move in picking.move_ids:
                        # Tìm dòng pos.order.line tương ứng với move này
                        line = order.lines.filtered(lambda l: l.product_id == move.product_id and l.qty < 0)
                        
                        if line and line[0].refunded_orderline_id:
                            original_line = line[0].refunded_orderline_id
                            original_order = original_line.order_id
                            
                            # Tìm vị trí xuất kho chi tiết ban đầu (Nơi mà đích đến là KHÁCH HÀNG)
                            # Đây là cách chính xác nhất để tìm cái kệ đã bốc hàng đi.
                            original_move_lines = original_order.picking_ids.move_line_ids.filtered(
                                lambda ml: ml.product_id == original_line.product_id 
                                and ml.location_dest_id.usage == 'customer'
                                and ml.quantity > 0
                            )
                            
                            if original_move_lines:
                                target_location = original_move_lines[0].location_id
                                if target_location:
                                    _logger.info("POS Return: Found ORIGINAL SHELF %s for product %s", 
                                               target_location.complete_name, move.product_id.name)
                                    
                                    # Cập nhật vị trí đích của move hoàn tiền
                                    move.write({'location_dest_id': target_location.id})
                                    if move.move_line_ids:
                                        move.move_line_ids.write({'location_dest_id': target_location.id})
                            else:
                                _logger.warning("POS Return: Could not find original shipping move line for %s", move.product_id.name)
        return res
