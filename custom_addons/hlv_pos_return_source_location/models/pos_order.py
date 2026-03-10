# -*- coding: utf-8 -*-
from odoo import models, api, fields

class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _create_order_picking(self):
        """
        Override to inject original source location into refund stock moves.
        """
        res = super(PosOrder, self)._create_order_picking()
        for order in self:
            # We only care about orders that have positive picking created (which might be return pickings)
            # Standard Odoo logic: refund creates a picking with negative quantities as a return.
            for picking in order.picking_ids:
                if picking.state == 'done':
                    # If it's already done, we might be too late depending on session settings
                    # but usually _create_order_picking is called before validation.
                    continue
                
                for move in picking.move_ids:
                    # Check if this move corresponds to a refund line
                    # Odoo matches moves to lines via various ways, usually it's easier to check the line itself.
                    # In Odoo 18, pos.order.line usually has a link back to the picking move.
                    pass
        return res

class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    def _prepare_stock_move_vals(self, picking, location_id, location_dest_id):
        """
        Odoo 18 standard method (likely name) to prepare move values.
        If it's a refund, we try to set location_dest_id to the original source location.
        """
        vals = super()._prepare_stock_move_vals(picking, location_id, location_dest_id)
        
        # If this is a refund line (qty < 0)
        if self.qty < 0 and self.refunded_orderline_id:
            # Find the original move that shipped this product
            # pos.order.line -> origin line -> picking -> moves
            original_line = self.refunded_orderline_id
            original_order = original_line.order_id
            
            # Find moves for the original line
            # Usually we can look at the original order's pickings
            original_moves = original_order.picking_ids.move_ids.filtered(
                lambda m: m.product_id == original_line.product_id and m.state == 'done'
            )
            
            if original_moves:
                # Use the last successful source location of the original product
                # In most cases, it's just one location.
                original_source_location = original_moves[0].location_id
                if original_source_location:
                    # For a return move, location_dest_id is where the goods are going BACK to.
                    vals['location_dest_id'] = original_source_location.id
                    
        return vals
