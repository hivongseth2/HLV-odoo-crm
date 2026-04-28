import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class AmisCallbackController(http.Controller):
    @http.route([
        '/api/oauth/actopensupport/call_back_data_demo',
        '/api/oauth/actopensupport/call_back_data',
    ], type='http', auth='public', methods=['POST'], csrf=False)
    def amis_callback(self, **kwargs):
        try:
            raw_body = request.httprequest.get_data(as_text=True) or ''
            payload = request.httprequest.get_json(silent=True)
            if payload is None and raw_body:
                try:
                    payload = json.loads(raw_body)
                except Exception:
                    payload = None

            if not isinstance(payload, dict):
                _logger.warning("AMIS callback received invalid JSON body: %s", raw_body)
                request.env['amis.callback.log'].sudo().create_from_payload(
                    payload={},
                    raw_body=raw_body,
                    request_path=request.httprequest.path,
                    remote_addr=request.httprequest.remote_addr,
                    parse_error='Invalid JSON payload',
                )
                return request.make_json_response({
                    "Success": False,
                    "ErrorCode": "InvalidParam",
                    "ErrorMessage": "Invalid JSON payload",
                })

            response = request.env['amis.callback.log'].sudo().create_from_payload(
                payload=payload,
                raw_body=raw_body,
                request_path=request.httprequest.path,
                remote_addr=request.httprequest.remote_addr,
            )
            return request.make_json_response(response)

        except Exception as e:
            _logger.exception("Exception in AMIS callback")
            try:
                request.env['amis.callback.log'].sudo().create_from_payload(
                    payload={},
                    raw_body=request.httprequest.get_data(as_text=True) or '',
                    request_path=request.httprequest.path,
                    remote_addr=request.httprequest.remote_addr,
                    parse_error=str(e),
                )
            except Exception:
                _logger.exception("Failed to persist AMIS callback error log")
            return request.make_json_response({
                "Success": False,
                "ErrorCode": "Exception",
                "ErrorMessage": str(e)
            })

    def _generate_signature(self, data_string, key):
        if not data_string:
            data_string = ""
        digest = hmac.new(
            key.encode("utf-8"),
            msg=data_string.encode("utf-8"),
            digestmod=hashlib.sha256
        ).hexdigest()
        return digest
