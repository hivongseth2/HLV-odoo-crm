# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from datetime import date, datetime

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_assign(self):
        """
        Override to implement "Priority Reservation" logic.
        If current picking can't reserve enough stock, try to find other pickings
        that are holding stock but have a further deadline (x_studio_hn_giao_hng),
        and unreserve them.
        """
        # 1. Standard assign first to see what we can get normally
        res = super(StockPicking, self).action_assign()
        
        # 2. Check if we need to steal stock
        # Process only pickings that are NOT fully done/cancel
        for picking in self:
            if picking.state in ['done', 'cancel']:
                continue
                
            # Check if fully reserved. 
            # We check if there are any moves that are 'confirmed' (waiting) or 'partially_available'
            # and demand > reserved.
            moves_missing_stock = picking.move_ids_without_package.filtered(
                lambda m: m.state in ['confirmed', 'partially_available'] and m.product_uom_qty > sum(m.move_line_ids.mapped('quantity'))
            )
            
            if moves_missing_stock:
                self._steal_stock_from_later_deadlines(picking, moves_missing_stock)
            
        return res

    def _steal_stock_from_later_deadlines(self, picking, moves_needing_stock):
        """
        Logic to find victims and unreserve them.
        """
        for move in moves_needing_stock:
            reserved_qty = sum(move.move_line_ids.mapped('quantity'))
            qty_needed = move.product_uom_qty - reserved_qty
            if qty_needed <= 0:
                continue

            product = move.product_id
            location_id = move.location_id
            
            # Find candidate moves to unreserve
            # We look for moves:
            # - Same product
            # - Same location
            # - Picking is NOT this picking
            # - Picking state is assigned or partially available
            # - Victim picking (picking_id) exists
            
            domain = [
                ('product_id', '=', product.id),
                ('location_id', '=', location_id.id),
                ('state', 'in', ['assigned', 'partially_available']),
                ('picking_id', '!=', False),
                ('picking_id', '!=', picking.id),
                ('picking_id.state', 'in', ['assigned', 'partially_available']),
            ]
            
            # Fetch candidates
            candidate_moves = self.env['stock.move'].search(domain)
            
            if not candidate_moves:
                continue
                
            # Filter and Sort candidates in Python
            # Reason: x_studio_hn_giao_hng might be a date or False.
            
            def get_sort_key(m):
                # We want pickings with FURTHEST deadline to be first in the list (so we unreserve them first).
                # If No Deadline (False), we treat it as infinite future (Very high priority to unreserve).
                # So we want False > Future Date > Near Date.
                # If we sort by date normally: 2026 > 2025. False is usually minimal.
                # So we need a custom key.
                
                deadline = getattr(m.picking_id, 'x_studio_hn_giao_hng', False)
                if not deadline:
                    return date.max # Max date acts as Infinity
                return deadline

            # Sort DESCENDING: Max Date (Infinity/False) -> Future -> Near
            sorted_candidates = sorted(candidate_moves, key=get_sort_key, reverse=True)
            
            qty_freed = 0
            moves_reassigned = False
            
            for cand in sorted_candidates:
                # Calculate how much we can take from this candidate
                cand_reserved = sum(cand.move_line_ids.mapped('quantity'))
                can_take = cand_reserved
                if can_take <= 0:
                    continue
                
                # We only need enough to fill our gap
                take_amount = min(can_take, qty_needed - qty_freed)
                
                # Unreserve logic
                # calling _do_unreserve() on stock.move unreserves EVERYTHING on that move usually.
                # It doesn't support partial unreserve easily without explicit splitting.
                # For simplicity, we unreserve the whole move. 
                # If we unreserve too much, it's fine, it becomes available for others (or us).
                
                try:
                    cand._do_unreserve()
                    
                    # Log
                    cand.picking_id.message_post(body=_(
                        "System automatically unreserved %s units of %s to prioritize picking %s (Reason: Deadline comparison)."
                    ) % (can_take, product.display_name, picking.name))
                    
                    qty_freed += can_take
                    moves_reassigned = True
                except Exception as e:
                    continue

                if qty_freed >= qty_needed:
                    break
            
            # Re-assign OUR move if we freed anything
            if moves_reassigned:
                try:
                    move._action_assign()
                except Exception:
                    pass
