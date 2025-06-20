from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class AmisCallbackController(http.Controller):

    @http.route('/api/amis/callback', type='http', auth='public', methods=['POST'], csrf=False)
    def amis_callback(self, **kwargs):
        try:
            json_data = request.httprequest.get_json(force=True, silent=True)
            _logger.info("Received AMIS callback RAW BODY: %s", request.httprequest.get_data())
            _logger.info("Parsed JSON: %s", json_data)
            return request.make_json_response({"Success": True})
        except Exception as e:
            _logger.exception("Failed to parse AMIS callback")
            return request.make_json_response({"Success": False, "Error": str(e)}, status=400)
