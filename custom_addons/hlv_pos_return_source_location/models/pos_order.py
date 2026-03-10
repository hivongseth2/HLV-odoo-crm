# -*- coding: utf-8 -*-
from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)

class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _create_order_picking(self):
        """
        Log xem kết quả cuối cùng Odoo tạo ra sau khi đã được StockPicking xử lý.
        """
        _logger.info("DEBUG: Entering _create_order_picking for Order: %s", self.name)
        res = super(PosOrder, self)._create_order_picking()
        
        for order in self:
            for picking in order.picking_ids:
                _logger.info("DEBUG FINAL: Picking %s Dest: %s (State: %s)", 
                           picking.name, picking.location_dest_id.complete_name, picking.state)
                for move in picking.move_ids:
                    _logger.info("DEBUG FINAL: Move %s Dest: %s", 
                               move.product_id.name, move.location_dest_id.complete_name)

        return res
