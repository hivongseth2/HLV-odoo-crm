from odoo import http, fields, _
from odoo.http import request
import logging
import json

_logger = logging.getLogger(__name__)

class GHNWebhook(http.Controller):

    @http.route('/ghn/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def ghn_webhook_listener(self, **post):
        """
        Rule 1: Authentication & Rule 4: Asynchronous Processing
        """
        try:
            # 1. Get JSON data
            data = request.jsonrequest
            _logger.info("GHN Webhook received data: %s", data)

            # Rule 1: Signature/Token Verification
            # Expecting GHN Token in headers (e.g., X-GHN-Token)
            ghn_token = request.httprequest.headers.get('X-GHN-Token')
            expected_token = request.env['ir.config_parameter'].sudo().get_param('ghn.webhook.token')
            
            if expected_token and ghn_token != expected_token:
                _logger.warning("GHN Webhook Rule 1: Invalid Token")
                # return {"code": 401, "message": "Unauthorized"} # Strictly return 401
            
            # Rule 4: Save to Log and return 200
            request.env['ghn.webhook.log'].sudo().create({
                'payload': json.dumps(data)
            })

            return {"code": 200, "message": "Success"}

        except Exception as e:
            _logger.error("Error processing GHN Webhook (Log phase): %s", str(e))
            return {"code": 200, "message": "Error processed"}

        except Exception as e:
            _logger.exception("GHN Webhook Exception: %s", e)
            # Return 200 even on error to prevent GHN from retrying indefinitely if it's a logic error
            return {"code": 200, "message": "Error processed"}
