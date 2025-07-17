from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class CustomBarcodeScanController(http.Controller):

    @http.route(['/custom_barcode_scan/ui'], type='http', auth='user')
    def scan_ui(self):
        return request.render("custom_barcode_scan_redirect.scan_ui_template")

    @http.route('/custom_barcode_scan/ui/scan', type='json', auth='user', csrf=False)
    def scan_ui_api(self, **kwargs):
        barcode = kwargs.get("barcode")
        _logger.info(f"[SCAN] Barcode: {barcode}")

        Picking = request.env['stock.picking'].sudo()
        picking = Picking.search([('name', '=', barcode)], limit=1)

        if not picking:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Không tìm thấy phiếu với mã: {barcode}",
                    'type': 'danger',
                    'sticky': False,
                }
            }

        if picking.state == 'done' and picking.group_id:
            next_picking = Picking.search([
                ('group_id', '=', picking.group_id.id),
                ('id', '!=', picking.id),
                ('state', 'in', ['confirmed', 'assigned', 'waiting'])
            ], limit=1)
            if next_picking:
                picking = next_picking
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': "Không tìm thấy phiếu liên kết tiếp theo!",
                        'type': 'warning',
                        'sticky': False,
                    }
                }

        return {
            'type': 'ir.actions.client',
            'tag': 'stock_barcode_client_action',
            'target': 'fullscreen',
            'params': {
                'model': 'stock.picking',
                'res_id': picking.id,
            }
        }
