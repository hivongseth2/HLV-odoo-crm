from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class AmisCallbackController(http.Controller):

    @http.route('/api/amis/callback', type='json', auth='public', methods=['POST'], csrf=False)
    def amis_callback(self, **post):
            _logger.info("Received AMIS callback RAW BODY: %s", request.httprequest.get_data())
            _logger.info("Parsed JSON: %s", post)
            return {"Success": True}
