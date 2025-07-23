from odoo import models

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_redirect_to_pack(self):
        self.ensure_one()
        pack = self.env['stock.picking'].search([
            ('origin', '=', self.name),
            ('state', 'not in', ['done', 'cancel']),
            ('picking_type_id.code', '=', 'outgoing')
        ], limit=1)
        if pack:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'view_mode': 'form',
                'res_id': pack.id,
                'target': 'current',
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Pack Found',
                    'message': 'Không tìm thấy phiếu pack liên quan chưa done.',
                    'type': 'warning',
                    'sticky': False,
                }
            }
