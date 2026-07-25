# -*- coding: utf-8 -*-
from odoo import models, fields


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _action_done(self):
        """
        Override _action_done to propagate POS fields to newly created
        downstream pickings when a step is validated.
        
        In 3-step delivery (Pick → Pack → Out):
        - When Pick is validated, Pack picking is created → propagate POS fields
        - When Pack is validated, Out picking is created → propagate POS fields
        """
        res = super(StockPicking, self)._action_done()

        for picking in self:
            # Only propagate if this picking has POS fields
            pos_group = getattr(picking, 'x_studio_pos_group', False)
            pos_payment = getattr(picking, 'x_studio_pos_payment_method', False)
            if not pos_group and not pos_payment:
                continue

            # Find downstream pickings via move_dest_ids
            dest_moves = picking.move_ids.mapped('move_dest_ids')
            downstream_pickings = dest_moves.mapped('picking_id') - picking
            
            for dp in downstream_pickings:
                vals = {}
                if pos_group and hasattr(dp, 'x_studio_pos_group') and not dp.x_studio_pos_group:
                    vals['x_studio_pos_group'] = pos_group
                if pos_payment and hasattr(dp, 'x_studio_pos_payment_method') and not dp.x_studio_pos_payment_method:
                    vals['x_studio_pos_payment_method'] = pos_payment
                if vals:
                    dp.write(vals)

        return res
