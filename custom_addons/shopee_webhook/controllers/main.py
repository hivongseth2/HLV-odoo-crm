# -*- coding: utf-8 -*-
import json
import os
import logging
from datetime import datetime
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Log file path - persistent file, won't be rotated by Odoo
_SHOPEE_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
_SHOPEE_LOG_FILE = os.path.join(_SHOPEE_LOG_DIR, 'shopee_webhook.log')


def _write_to_log_file(message):
    """Write a message to the persistent Shopee webhook log file."""
    try:
        os.makedirs(_SHOPEE_LOG_DIR, exist_ok=True)
        with open(_SHOPEE_LOG_FILE, 'a', encoding='utf-8') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        _logger.error("Failed to write to Shopee log file: %s", str(e))


class ShopeeWebhookController(http.Controller):

    @http.route('/shopee/webhook/delivery', type='json', auth='public', methods=['POST'], csrf=False)
    def shopee_delivery_webhook(self, **kwargs):
        """
        PRD Endpoint: Receive Shopee booking_status_push only.
        - NO database writes (no create/update/delete).
        - Logs all received data to a persistent file for review.
        """
        try:
            # Get JSON data from request
            data = request.get_json_data()

            # Log raw payload to persistent file
            _write_to_log_file(f"RAW PAYLOAD: {json.dumps(data, ensure_ascii=False)}")

            if not data:
                _write_to_log_file("WARN: Empty payload received")
                return {'code': 1, 'msg': 'Empty payload'}

            # Only process booking_status_push, ignore everything else
            push_code = data.get('code') or data.get('push_code') or data.get('type', '')
            _write_to_log_file(f"PUSH CODE: {push_code}")

            if push_code and str(push_code) != 'booking_status_push':
                _write_to_log_file(f"IGNORED: push_code='{push_code}' is not booking_status_push")
                return {'code': 0, 'msg': f'Ignored push_code: {push_code}'}

            # Extract key info for logging (NO DB writes)
            ordersn = (
                data.get('ordersn')
                or data.get('order_sn')
                or (data.get('data', {}) or {}).get('ordersn')
                or (data.get('data', {}) or {}).get('order_sn')
            )
            status = (
                data.get('status')
                or data.get('booking_status')
                or (data.get('data', {}) or {}).get('status')
                or (data.get('data', {}) or {}).get('booking_status')
            )
            tracking_no = (
                data.get('tracking_no')
                or data.get('tracking_number')
                or (data.get('data', {}) or {}).get('tracking_no')
                or (data.get('data', {}) or {}).get('tracking_number')
            )

            _write_to_log_file(
                f"PARSED: ordersn={ordersn}, status={status}, tracking_no={tracking_no}"
            )

            # Pretty print the full data for easier review
            _write_to_log_file(f"FULL DATA:\n{json.dumps(data, indent=2, ensure_ascii=False)}")
            _write_to_log_file("-" * 80)

            return {'code': 0, 'msg': 'Logged successfully (PRD read-only mode)'}

        except Exception as e:
            error_msg = f"ERROR: {str(e)}"
            _write_to_log_file(error_msg)
            _logger.error("Error processing Shopee Webhook: %s", str(e), exc_info=True)
            return {'code': 3, 'msg': str(e)}
