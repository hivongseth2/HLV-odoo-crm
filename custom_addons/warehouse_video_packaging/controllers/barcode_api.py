from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

class WarehouseVideoAPI(http.Controller):

    @http.route(
        '/warehouse_video_packaging/api/scan_pick',
        type='http', auth='public', methods=['POST'], csrf=False
    )
    def api_scan_pick(self, **kwargs):
        # Lấy barcode từ body JSON hoặc form-urlencoded
        try:
            # Ưu tiên JSON nếu có
            data = json.loads(request.httprequest.data.decode('utf-8') or '{}')
        except Exception:
            data = {}
        
        barcode = data.get('barcode') or kwargs.get('barcode')

        if not barcode:
            return request.make_response(
                json.dumps({"error": "Missing barcode"}),
                headers=[('Content-Type', 'application/json')],
                status=400
            )

        _logger.info(f"🔓 [API] Gọi PUBLIC API scan_pick | Barcode: {barcode}")

        picking = request.env['stock.picking'].sudo().search([('name', '=', barcode)], limit=1)
        if not picking:
            return request.make_response(
                json.dumps({"error": f"No picking found for barcode {barcode}"}),
                headers=[('Content-Type', 'application/json')],
                status=404
            )

        if picking.video_state == 'idle':
            _logger.info(f"🎥 [API] Bắt đầu quay video cho {picking.name}")
            picking.action_put_in_pack()
            return request.make_response(
                json.dumps({"result": f"Started recording for {picking.name}"}),
                headers=[('Content-Type', 'application/json')],
                status=200
            )
        else:
            return request.make_response(
                json.dumps({"result": f"Picking {picking.name} video state is {picking.video_state}"}),
                headers=[('Content-Type', 'application/json')],
                status=200
            )
