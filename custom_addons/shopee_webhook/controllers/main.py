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


def _log_to_file(data):
    """Ghi raw data vào file log persistent."""
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_LOG_FILE, 'a', encoding='utf-8') as f:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{ts}] {json.dumps(data, ensure_ascii=False)}\n")
    except Exception as e:
        _logger.error("Failed to write Shopee log file: %s", str(e))

class ShopeeWebhookController(http.Controller):

    @http.route('/shopee/webhook/delivery', type='json', auth='public', methods=['POST'], csrf=False)
    def shopee_delivery_webhook(self, **kwargs):
        """
        Endpoint to receive Shopee delivery status updates.
        Expected payload format (based on common Shopee pushes - Subject to verification):
        {
            "data": {
                "ordersn": "ORDER_ID",
                "status": "STATUS",
                ...
            },
            ...
        }
        """
        try:
            # Get JSON data from request
            data = request.get_json_data()
            _logger.info("Received Shopee Webhook Data: %s", json.dumps(data))

            # Ghi vào file log persistent
            _log_to_file(data)

            if not data:
                 return {'code': 1, 'msg': 'Empty payload'}

            # The payload structure usually has a 'data' key or matches generic format.
            # Adjust these keys based on actual Shopee documentation if needed.
            # Assuming 'ordersn' is the key for Order SN (Shopee Order Ref).
            
            # Helper to find value recursively if structure is unknown or nested
            def find_value(json_obj, key):
                if isinstance(json_obj, dict):
                    if key in json_obj:
                        return json_obj[key]
                    for k, v in json_obj.items():
                        res = find_value(v, key)
                        if res: return res
                elif isinstance(json_obj, list):
                    for item in json_obj:
                        res = find_value(item, key)
                        if res: return res
                return None

            # Try to grab 'ordersn' (Order SN) and 'status' (Delivery Status)
            # Possible keys for order ID: 'ordersn', 'order_sn'
            ordersn = find_value(data, 'ordersn') or find_value(data, 'order_sn')
            
            # Possible keys for status: 'status', 'tracking_status', 'logistics_status'
            status = find_value(data, 'status') or find_value(data, 'tracking_status') or find_value(data, 'logistics_status')

            # Possible keys for tracking number: 'tracking_no', 'tracking_number'
            tracking_no = find_value(data, 'tracking_no') or find_value(data, 'tracking_number')

            if not ordersn and not tracking_no:
                _logger.warning("Shopee Webhook: Could not find 'ordersn' or 'tracking_no' in payload.")
                return {'code': 2, 'msg': 'Missing identifier'}

            # Find the Sale Order
            orders = request.env['sale.order'].sudo()
            if ordersn:
                # 1. Try finding by Shopee Order Ref (Mã đơn hàng)
                orders = request.env['sale.order'].sudo().search([('shopee_order_ref', '=', ordersn)])
            
            if not orders and tracking_no:
                # 2. If not found by Order Ref, try finding by Tracking Number (Mã vận đơn) in Stock Picking
                # Note: carrier_tracking_ref is on stock.picking
                pickings = request.env['stock.picking'].sudo().search([('carrier_tracking_ref', '=', tracking_no)])
                if pickings:
                    # Get sale orders related to these pickings
                    orders = pickings.mapped('sale_id')

            if not orders:
                _logger.warning("Shopee Webhook: Order not found for identifier: %s / %s", ordersn, tracking_no)
                # We return success code to Shopee so they VALIDATE the push, even if we don't have the order.
                # Otherwise they might retry indefinitely.
                return {'code': 0, 'msg': 'Order not found, but processed'}

            for order in orders:
                if status:
                    old_status = order.shopee_order_status
                    order.write({'shopee_order_status': status})
                    _logger.info("Shopee Webhook: Updated Order %s status from '%s' to '%s'", order.name, old_status, status)
                else:
                    _logger.info("Shopee Webhook: No status update found in payload for Order %s", order.name)

            return {'code': 0, 'msg': 'success'}

        except Exception as e:
            _logger.error("Error processing Shopee Webhook: %s", str(e), exc_info=True)
            return {'code': 3, 'msg': str(e)}

    @http.route('/shopee/webhook/logs', type='http', auth='user', methods=['GET'])
    def shopee_webhook_logs(self, lines=200, **kwargs):
        """Xem log webhook qua trình duyệt: /shopee/webhook/logs?lines=500"""
        try:
            if not os.path.exists(_LOG_FILE):
                content = 'No log file yet.'
            else:
                with open(_LOG_FILE, 'r', encoding='utf-8') as f:
                    all_lines = f.readlines()
                    content = ''.join(all_lines[-int(lines):])
            return request.make_response(
                content,
                headers=[('Content-Type', 'text/plain; charset=utf-8')]
            )
        except Exception as e:
            return request.make_response(str(e), headers=[('Content-Type', 'text/plain')])
