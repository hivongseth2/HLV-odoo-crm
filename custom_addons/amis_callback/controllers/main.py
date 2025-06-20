from odoo import http
from odoo.http import request
import hmac
import hashlib
import logging

_logger = logging.getLogger(__name__)

class AmisCallbackController(http.Controller):
    _app_id = "0e0a14cf-9e4b-4af9-875b-c490f34a581b"  # Thay bằng app_id thật khi triển khai

    @http.route('/api/amis/callback', type='http', auth='public', methods=['POST'], csrf=False)
    def amis_callback(self, **kwargs):
        try:
            raw_body = request.httprequest.get_data()
            data = request.httprequest.get_json(force=True, silent=True)
            _logger.info("Received AMIS callback RAW BODY: %s", raw_body)
            _logger.info("Parsed JSON: %s", data)

            expected_signature = self._generate_signature(data.get("data", ""), self._app_id)
            if data.get("signature") != expected_signature:
                return request.make_json_response({
                    "Success": False,
                    "ErrorCode": "InvalidParam",
                    "ErrorMessage": "Signature invalid"
                }, status=400)

            return request.make_json_response({"Success": True, "ErrorMessage": ""})

        except Exception as e:
            _logger.exception("Exception in callback")
            return request.make_json_response({
                "Success": False,
                "ErrorCode": "Exception",
                "ErrorMessage": str(e)
            }, status=500)

    def _generate_signature(self, data_string, key):
        if not data_string:
            data_string = ""
        digest = hmac.new(
            key.encode("utf-8"),
            msg=data_string.encode("utf-8"),
            digestmod=hashlib.sha256
        ).hexdigest()
        return digest
