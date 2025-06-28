from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class WarehouseVideoAPI(http.Controller):
    @http.route(['/warehouse_video_packaging/api/scan_pick'], type='json', auth='public', methods=['POST'], csrf=False)
    def api_scan_pick(self, **post):
        barcode = post.get('barcode')
        if not barcode:
            return {"error": "Missing barcode"}

        _logger.info(f"🔓 [API] Gọi PUBLIC API scan_pick | Barcode: {barcode}")

        picking = request.env['stock.picking'].sudo().search([('name', '=', barcode)], limit=1)
        if not picking:
            return {"error": f"No picking found for barcode {barcode}"}

        if picking.video_state == 'idle':
            _logger.info(f"🎥 [API] Bắt đầu quay video cho {picking.name}")
            picking.action_put_in_pack()
            return {"result": f"Started recording for {picking.name}"}
        else:
            return {"result": f"Picking {picking.name} video state is {picking.video_state}"}
