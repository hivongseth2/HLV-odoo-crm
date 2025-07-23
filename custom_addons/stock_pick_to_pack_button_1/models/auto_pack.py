from odoo import models

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_done(self):
        res = super(StockPicking, self).action_done()
        if self.picking_type_id.code in ['internal', 'outgoing']:
            next_picking = self.env['stock.picking'].search([
                ('state', '=', 'assigned'),
                ('picking_type_id.code', '=', 'outgoing'),
                ('origin', '=', self.origin)
            ], limit=1)
            if next_picking:
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'stock.picking',
                    'res_id': next_picking.id,
                    'view_mode': 'form',
                    'target': 'current',
                }
        return res