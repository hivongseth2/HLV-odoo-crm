from odoo.addons.stock_barcode.controllers.main import StockBarcodeController
from odoo.http import route, request
import json

class CustomBarcodeController(StockBarcodeController):

    @route('/barcode/scanner', type='json', auth='user')
    def barcode_scanner(self, barcode):
        res = super().barcode_scanner(barcode)

        if res.get('error') == 'No result found':
            pick = request.env['stock.picking'].sudo().search([
                ('name', '=', barcode),
                ('state', '=', 'done')
            ], limit=1)

            if pick:
                pack = request.env['stock.picking'].sudo().search([
                    ('origin', '=', pick.name),
                    ('state', 'not in', ['done', 'cancel']),
                    ('picking_type_id.code', '=', 'outgoing')
                ], limit=1)

                if pack:
                    return {
                        'type': 'picking',
                        'res_id': pack.id,
                        'action': '/stock_barcode/' + str(pack.id)
                    }

                return {'error': 'Không tìm thấy phiếu pack liên quan'}

        return res
