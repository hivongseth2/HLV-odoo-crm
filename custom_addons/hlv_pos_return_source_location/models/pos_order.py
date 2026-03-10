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
                
                _logger.info("DEBUG POS Return PREPARE for Product %s. Original Order: %s", 
                            line.product_id.name, orig_order.name)
                
                # Tìm tất cả move lines của đơn gốc để xem nó là cái gì
                all_ml = orig_order.sudo().picking_ids.move_line_ids.filtered(
                    lambda ml: ml.product_id == line.product_id and ml.quantity > 0
                )
                
                for ml in all_ml:
                    _logger.info("DEBUG Original ML: ID %s, Product %s, Qty %s, From %s, To %s (Usage To: %s)", 
                                ml.id, ml.product_id.name, ml.quantity, ml.location_id.complete_name, 
                                ml.location_dest_id.complete_name, ml.location_dest_id.usage)

                # Tìm kệ gốc: Lấy Move Line nào có đích đến là 'customer' HOẶC 'transit' HOẶC là move cuối cùng của picking xuất
                # Nếu không thấy 'customer', ta lấy cái nào có location_id sâu nhất (chứa dấu / nhiều nhất)
                orig_move_lines = all_ml.filtered(lambda ml: ml.location_dest_id.usage == 'customer')
                
                if not orig_move_lines:
                    # Nếu không có customer, lấy cái cuối cùng trong danh sách (thường là picking xuất)
                    orig_move_lines = all_ml
                
                if orig_move_lines:
                    # Sắp xếp để lấy cái kệ chi tiết nhất (depth cao nhất)
                    target_ml = sorted(orig_move_lines, key=lambda x: len(x.location_id.complete_name.split('/')), reverse=True)[0]
                    target_loc = target_ml.location_id
                    
                    if target_loc:
                        _logger.info("POS Return PREPARE: SUCCESS! Redirecting to Shelf [%s]", target_loc.complete_name)
                        res['location_dest_id'] = target_loc.id
                else:
                    _logger.warning("POS Return PREPARE: FAILED to find any move lines for original order")
            except Exception as e:
                _logger.error("POS Return PREPARE error: %s", str(e), exc_info=True)
                
        return res

    def _create_order_picking(self):
        """
        Log xem kết quả cuối cùng Odoo tạo ra.
        """
        _logger.info("DEBUG: Entering _create_order_picking for Order: %s", self.name if len(self)==1 else "Multiple")
        res = super(PosOrder, self)._create_order_picking()
        
        for order in self:
            for picking in order.picking_ids:
                _logger.info("DEBUG FINAL: Picking %s Dest: %s", picking.name, picking.location_dest_id.complete_name)
                for move in picking.move_ids:
                    _logger.info("DEBUG FINAL: Move %s Dest: %s", move.product_id.name, move.location_dest_id.complete_name)

        return res
