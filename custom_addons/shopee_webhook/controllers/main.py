# -*- coding: utf-8 -*-
import json
import os
import logging
from datetime import datetime
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
_LOG_FILE = os.path.join(_LOG_DIR, 'shopee_webhook.log')


class ShopeeWebhookController(http.Controller):

    @http.route('/shopee/webhook/delivery', type='json', auth='public', methods=['POST'], csrf=False)
    def shopee_delivery_webhook(self, **kwargs):
        try:
            data = request.get_json_data()
            if not data or data.get('code') != 23:
                return {'code': 0, 'msg': 'ignored'}
            os.makedirs(_LOG_DIR, exist_ok=True)
            with open(_LOG_FILE, 'a', encoding='utf-8') as f:
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"[{ts}] {json.dumps(data, ensure_ascii=False)}\n")
            return {'code': 0, 'msg': 'ok'}
        except Exception as e:
            _logger.error("Shopee Webhook error: %s", str(e), exc_info=True)
            return {'code': 3, 'msg': str(e)}
