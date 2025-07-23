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
                'type': 'ir.actions.client',
                'tag': 'barcode_picking_client_action',
                'params': {
                    'barcode_picking_id': pack.id
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Không tìm thấy phiếu Pack',
                    'message': 'Không có phiếu Pack tương ứng chưa hoàn thành.',
                    'sticky': False,
                }
            }
