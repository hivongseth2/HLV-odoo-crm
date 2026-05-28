from odoo import models

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def copy_move_lines(self, source_picking, target_picking):
        """
        Override copy_move_lines to fix the Step 2 picking initialization.
        The default deltatech_picking_transit logic copies product_uom_qty=0 and quantity=X.
        We fix it here so that product_uom_qty=X and quantity=0, allowing users to scan and confirm.
        """
        # Call the parent/original copy_move_lines if it exists
        res = None
        if hasattr(super(), 'copy_move_lines'):
            res = super().copy_move_lines(source_picking, target_picking)
            
        # Fix target_picking move lines
        for move in target_picking.move_ids:
            if move.state == 'draft':
                # Sum the quantities assigned by the base copy_move_lines
                total_qty = sum(l.quantity for l in move.move_line_ids)
                if total_qty > 0:
                    move.product_uom_qty = total_qty
                    for line in move.move_line_ids:
                        line.quantity = 0.0
                        
        return res
