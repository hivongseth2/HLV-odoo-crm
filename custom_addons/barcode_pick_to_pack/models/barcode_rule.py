from odoo import models

class BarcodeRule(models.Model):
    _inherit = 'barcode.rule'

    def _get_action(self, barcode, active_model=None, active_id=None):
        action = super()._get_action(barcode, active_model, active_id)

        if not action:
            pick = self.env['stock.picking'].sudo().search([
                ('name', '=', barcode),
                ('state', '=', 'done')
            ], limit=1)

            if pick:
                pack = self.env['stock.picking'].sudo().search([
                    ('origin', '=', pick.name),
                    ('state', 'not in', ['done', 'cancel']),
                    ('picking_type_id.code', '=', 'outgoing')
                ], limit=1)

                if pack:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'reload',
                        'params': {'barcode_picking_id': pack.id},
                    }

        return action
