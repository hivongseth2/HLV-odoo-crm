from odoo import http
from odoo.http import request

class BarcodeRedirectController(http.Controller):
    @http.route('/stock/barcode/redirect_to_pack', type='json', auth='user')
    def redirect_to_pack(self, origin):
        picking = request.env['stock.picking'].search([
            ('origin', '=', origin),
            ('state', 'not in', ['done', 'cancel']),
            ('picking_type_id.code', '=', 'outgoing'),
        ], limit=1)
        return picking.id if picking else False