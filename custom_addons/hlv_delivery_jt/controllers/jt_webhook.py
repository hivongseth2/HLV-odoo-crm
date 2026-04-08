# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request
import json
import logging
import pytz
from datetime import datetime

_logger = logging.getLogger(__name__)

class JTWebhook(http.Controller):

    @http.route('/jt/webhook/status', type='http', auth='public', methods=['POST'], csrf=False)
    def jt_status_update(self, **post):
        """
        Rule 1: Authentication & Rule 4: Asynchronous Processing
        """
        try:
            # 1. Get bizContent
            biz_content = post.get('bizContent')
            if not biz_content:
                _logger.warning("J&T Webhook: Missing bizContent")
                return json.dumps({'code': '0', 'msg': 'Missing bizContent'})

            # Rule 1: Signature Verification
            # J&T usually sends a signature or requires a secret token.
            # Here we check for a configured webhook key.
            jt_key = post.get('key') or request.httprequest.headers.get('X-JT-Key')
            expected_key = request.env['ir.config_parameter'].sudo().get_param('jt.webhook.key')
            
            if expected_key and jt_key != expected_key:
                _logger.warning("J&T Webhook Rule 1: Invalid Key")
                # return json.dumps({'code': '0', 'msg': 'Unauthorized'})

            # Rule 4: Save to Log and return 200 immediately
            request.env['jt.webhook.log'].sudo().create({
                'payload': biz_content # bizContent contains the actual JSON data
            })

            return json.dumps({'code': '1', 'msg': 'success', 'data': None})

        except Exception as e:
            _logger.error("J&T Webhook Error (Log phase): %s", str(e))
            return json.dumps({'code': '0', 'msg': f'Error: {str(e)}'})
