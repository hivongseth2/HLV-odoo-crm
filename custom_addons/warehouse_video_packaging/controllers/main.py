from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class StockBarcodeController(http.Controller):

    @http.route(['/stock_barcode/scan_from_main_menu'], type='json', auth='user')
    def scan_from_main_menu(self, barcode):
        _logger.info(f"🔍 CONTROLLER HOOK: Quét barcode: {barcode}")
        picking = request.env['stock.picking'].sudo().search([('name', '=', barcode)], limit=1)
        if picking and picking.video_state == 'idle':
            _logger.info(f"🎥 BẮT ĐẦU quay video cho {picking.name}")
            picking.action_put_in_pack()
        return request.env['stock.barcode.handler'].scan_from_main_menu(barcode)
