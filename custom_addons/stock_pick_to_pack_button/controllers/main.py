from odoo import http
from odoo.http import request

class StockBarcodeRedirect(http.Controller):

    @http.route('/stock_pick_to_pack_button/redirect', type='json', auth='user')
    def redirect_to_pack(self, picking_id):
        picking = request.env['stock.picking'].browse(picking_id)
        pack = request.env['stock.picking'].search([
            ('origin', '=', picking.name),
            ('state', 'not in', ['done', 'cancel']),
            ('picking_type_id.code', '=', 'outgoing')
        ], limit=1)
        if pack:
            return {
                'action': {
                    'type': 'ir.actions.client',
                    'tag': 'barcode_picking_client_action',
                    'params': {
                        'barcode_picking_id': pack.id,
                    },
                }
            }
        else:
            return {'warning': 'Không tìm thấy phiếu pack liên quan chưa done.'}
