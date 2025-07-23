from odoo import http
from odoo.http import request

class BarcodePickToPackController(http.Controller):

    @http.route('/barcode_pick_to_pack/find_pack', type='json', auth='user')
    def find_pack(self, origin):
        pack = request.env['stock.picking'].sudo().search([
            ('origin', '=', origin),
            ('state', 'not in', ['done', 'cancel']),
            ('picking_type_id.code', '=', 'outgoing')
        ], limit=1)
        return {'id': pack.id} if pack else {}
