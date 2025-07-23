from odoo import http
from odoo.http import request

class CustomBarcodeController(http.Controller):

    @http.route('/barcode/custom_scanner', type='json', auth='user')
    def custom_barcode_scanner(self, barcode):
        Picking = request.env['stock.picking'].sudo()

        # Tìm phiếu pick đã done
        pick = Picking.search([
            ('name', '=', barcode),
            ('state', '=', 'done')
        ], limit=1)

        if not pick:
            return {'error': 'Không tìm thấy phiếu pick đã hoàn tất.'}

        # Tìm phiếu pack liên quan chưa done
        pack = Picking.search([
            ('origin', '=', pick.name),
            ('state', 'not in', ['done', 'cancel']),
            ('picking_type_id.code', '=', 'outgoing')
        ], limit=1)

        if pack:
            return {
                'type': 'picking',
                'res_id': pack.id,
                'action': f'/stock_barcode/{pack.id}'
            }

        return {'error': 'Không tìm thấy phiếu pack chưa hoàn tất.'}
