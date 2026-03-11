# -*- coding: utf-8 -*-
import json
import os
import logging
import time
import hashlib
import hmac
from datetime import datetime

import requests as req_lib
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
_LOG_FILE = os.path.join(_LOG_DIR, 'shopee_webhook.log')


def _log_to_file(data, result=None):
    """Ghi data vào file log persistent, dễ đọc."""
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_LOG_FILE, 'a', encoding='utf-8') as f:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            push_code = data.get('code', '?') if isinstance(data, dict) else '?'
            shop_id = data.get('shop_id', '?') if isinstance(data, dict) else '?'
            f.write(f"{'=' * 60}\n")
            f.write(f"TIME     : {ts}\n")
            f.write(f"PUSH CODE: {push_code}\n")
            f.write(f"SHOP ID  : {shop_id}\n")
            if result:
                f.write(f"RESULT   : {result}\n")
            f.write(f"DATA     :\n{json.dumps(data, indent=2, ensure_ascii=False)}\n")
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

            # Ghi vào file log persistent (log trước khi xử lý)
            _log_to_file(data)

            if not data:
                 return {'code': 1, 'msg': 'Empty payload'}

            # Get Push Code
            push_code = data.get('code')
            if push_code not in (23, 30):
                return {'code': 0, 'msg': f'ignored (code={push_code})'}

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
                
                # 1b. Fallback to Odoo Order Name (especially useful for manual testing)
                if not orders:
                    orders = request.env['sale.order'].sudo().search([('name', '=', ordersn)])
                    
                # 1c. Fallback to Client Order Ref
                if not orders:
                    orders = request.env['sale.order'].sudo().search([('client_order_ref', '=', ordersn)])
            
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

            results_log = []
            for order in orders:
                if status:
                    old_status = order.shopee_order_status
                    order.write({
                        'shopee_order_status': status,
                        'shopee_delivery_status': status,
                    })
                    _logger.info("Shopee Webhook: Updated Order %s status from '%s' to '%s'", order.name, old_status, status)
                    results_log.append(f"Updated {order.name}: {old_status} -> {status}")

                    # --- Zalo Cancel Notification ---
                    if status == 'CANCELLED':
                        try:
                            order._shopee_send_zalo_cancel_notification()
                            _logger.info("Shopee Webhook: Sent cancel notification for Order %s", order.name)
                            results_log.append(f"Sent cancel notification for {order.name}")
                        except Exception as e:
                            _logger.error("Shopee Webhook: Cancel notification failed for %s: %s", order.name, str(e))
                            results_log.append(f"Cancel notification failed {order.name}: {str(e)}")
                else:
                    _logger.info("Shopee Webhook: No status update found in payload for Order %s", order.name)

                # --- Auto Validate Delivery Order ---
                if push_code == 30 and status == 'LOGISTICS_DELIVERY_DONE':
                    # Find outging picking for this order
                    pickings_to_validate = request.env['stock.picking'].sudo().search([
                        ('sale_id', '=', order.id),
                        ('picking_type_id.code', '=', 'outgoing'),
                        ('state', 'in', ['confirmed', 'assigned'])
                    ])
                    for pick in pickings_to_validate:
                        try:
                            # 1. Assign (Reserve) if not assigned
                            if pick.state == 'confirmed':
                                pick.action_assign()
                            
                            # 2. Set Done Quantities to Reserved or Demanded Quantities
                            for move in pick.move_ids.filtered(lambda m: m.state not in ['done', 'cancel']):
                                # In Odoo 16/17/18, we can write directly on move line or move
                                if hasattr(move, 'move_line_ids') and move.move_line_ids:
                                    for line in move.move_line_ids:
                                        if hasattr(line, 'qty_done') and hasattr(line, 'reserved_uom_qty'):
                                            line.qty_done = line.reserved_uom_qty
                                        elif hasattr(line, 'quantity') and hasattr(line, 'quantity_product_uom'): # v17+
                                            line.quantity = line.quantity_product_uom
                                else:
                                    # Fallback to move level
                                    if hasattr(move, 'quantity_done'):
                                        move.quantity_done = move.product_uom_qty

                            # 3. Validate
                            # _action_done could trigger immediate transfer limits depending on Odoo version
                            # We use button_validate to go through standard UI flow checks if possible,
                            # or _action_done directly if we just want to force it.
                            res_validate = pick.button_validate()
                            if isinstance(res_validate, dict) and res_validate.get('res_model') == 'stock.immediate.transfer':
                                # Process immediate transfer wizard if it pops up
                                immediate_transfer = request.env['stock.immediate.transfer'].sudo().with_context(res_validate.get('context', {})).create({'pick_ids': [(4, pick.id)]})
                                immediate_transfer.process()
                            elif isinstance(res_validate, dict) and res_validate.get('res_model') == 'stock.backorder.confirmation':
                                # This shouldn't happen if we set qty_done = product_uom_qty, but just in case
                                backorder_conf = request.env['stock.backorder.confirmation'].sudo().with_context(res_validate.get('context', {})).create({'pick_ids': [(4, pick.id)]})
                                backorder_conf.process_cancel_backorder() # Do not create backorder

                            results_log.append(f"Auto-validated picking: {pick.name}")
                            _logger.info("Shopee Webhook: Auto-validated picking %s for order %s", pick.name, order.name)
                        except Exception as e:
                            _logger.error("Shopee Webhook: Auto-validate failed for %s: %s", pick.name, str(e))
                            results_log.append(f"Auto-validate failed {pick.name}: {str(e)}")

            if results_log:
                _log_to_file(data, result=" | ".join(results_log))

            return {'code': 0, 'msg': 'success'}

        except Exception as e:
            _logger.error("Error processing Shopee Webhook: %s", str(e), exc_info=True)
            _log_to_file(data if 'data' in dir() else {}, result=f"ERROR: {str(e)}")
            return {'code': 3, 'msg': str(e)}

    @http.route('/shopee/webhook/logs', type='http', auth='user', methods=['GET'])
    def shopee_webhook_logs(self, lines=100, **kwargs):
        """Xem log webhook qua trình duyệt: /shopee/webhook/logs?lines=50"""
        try:
            if not os.path.exists(_LOG_FILE):
                raw = 'Chưa có log nào.'
            else:
                with open(_LOG_FILE, 'r', encoding='utf-8') as f:
                    all_lines = f.readlines()
                    raw = ''.join(all_lines[-int(lines):])

            # Tách từng block log (phân cách bởi ====)
            import html as html_mod
            blocks = raw.split('=' * 60)
            entries_html = ''
            for block in reversed(blocks):
                block = block.strip()
                if not block:
                    continue
                # Xác định màu theo nội dung
                css_class = 'log-entry'
                if 'ERROR' in block:
                    css_class += ' log-error'
                elif 'Updated' in block:
                    css_class += ' log-success'
                entries_html += f'<div class="{css_class}"><pre>{html_mod.escape(block)}</pre></div>\n'

            if not entries_html:
                entries_html = '<p style="color:#888;">Chưa có log nào.</p>'

            page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Shopee Webhook Logs</title>
<style>
  body {{ font-family: 'Segoe UI', monospace; background: #1e1e2e; color: #cdd6f4; padding: 20px; }}
  h1 {{ color: #89b4fa; border-bottom: 1px solid #45475a; padding-bottom: 10px; }}
  .log-entry {{ background: #313244; border-left: 4px solid #89b4fa; padding: 12px 16px; margin: 8px 0; border-radius: 4px; }}
  .log-error {{ border-left-color: #f38ba8; background: #31222e; }}
  .log-success {{ border-left-color: #a6e3a1; background: #22312a; }}
  pre {{ margin: 0; white-space: pre-wrap; word-wrap: break-word; font-size: 13px; line-height: 1.5; }}
  .info {{ color: #a6adc8; font-size: 13px; margin-bottom: 16px; }}
</style></head><body>
<h1>📦 Shopee Webhook Logs</h1>
<div class="info">Hiển thị {lines} dòng gần nhất · Mới nhất ở trên · <a href="?lines=500" style="color:#89b4fa">Xem 500 dòng</a></div>
{entries_html}
</body></html>"""
            return request.make_response(page, headers=[('Content-Type', 'text/html; charset=utf-8')])
        except Exception as e:
            return request.make_response(str(e), headers=[('Content-Type', 'text/plain')])

    # ──────────────────────────────────────────────────────────────
    #  Shopee API Proxy – get_order_detail (read-only, no DB write)
    # ──────────────────────────────────────────────────────────────
    @http.route('/shopee/api/get_order_detail', type='http', auth='public', methods=['GET'], csrf=False)
    def shopee_get_order_detail(self, **kwargs):
        """
        Proxy endpoint gọi Shopee Open API v2/order/get_order_detail.
        Trả về raw JSON response từ Shopee. Không ghi gì vào DB.

        Query params:
            partner_id        (int, required)
            partner_key       (string, required) – để tạo sign
            access_token      (string, required)
            shop_id           (int, required)
            order_sn_list     (string, required) – danh sách order SN cách bởi dấu phẩy
            request_order_status_pending (string, optional) – "true"/"false"
            response_optional_fields     (string, optional)
        """
        try:
            # --- 1. Đọc params ---
            partner_id = kwargs.get('partner_id')
            partner_key = kwargs.get('partner_key')
            access_token = kwargs.get('access_token')
            shop_id = kwargs.get('shop_id')
            order_sn_list = kwargs.get('order_sn_list')

            if not all([partner_id, partner_key, access_token, shop_id, order_sn_list]):
                return request.make_response(
                    json.dumps({
                        'error': 'Missing required params',
                        'required': ['partner_id', 'partner_key', 'access_token', 'shop_id', 'order_sn_list'],
                    }),
                    headers=[('Content-Type', 'application/json')],
                )

            partner_id = int(partner_id)
            shop_id = int(shop_id)

            # --- 2. Tạo timestamp & sign (HMAC-SHA256) ---
            ts = int(time.time())
            api_path = '/api/v2/order/get_order_detail'
            # base_string = partner_id + api_path + timestamp + access_token + shop_id
            base_string = f"{partner_id}{api_path}{ts}{access_token}{shop_id}"
            sign = hmac.new(
                partner_key.encode('utf-8'),
                base_string.encode('utf-8'),
                hashlib.sha256,
            ).hexdigest()

            # --- 3. Gọi Shopee API ---
            shopee_url = 'https://partner.shopeemobile.com/api/v2/order/get_order_detail'
            params = {
                'partner_id': partner_id,
                'timestamp': ts,
                'access_token': access_token,
                'shop_id': shop_id,
                'sign': sign,
                'order_sn_list': order_sn_list,
            }

            # Optional params
            pending = kwargs.get('request_order_status_pending')
            if pending is not None:
                params['request_order_status_pending'] = pending

            opt_fields = kwargs.get('response_optional_fields')
            if opt_fields:
                params['response_optional_fields'] = opt_fields

            _logger.info("Shopee API call – get_order_detail params: %s", params)

            resp = req_lib.get(shopee_url, params=params, timeout=30)

            # --- 4. Trả raw response ---
            try:
                body = resp.json()
            except Exception:
                body = resp.text

            result = {
                'shopee_http_status': resp.status_code,
                'shopee_response': body,
                'request_params_sent': params,
            }

            _logger.info("Shopee API response – status=%s body=%s", resp.status_code, body)

            return request.make_response(
                json.dumps(result, indent=2, ensure_ascii=False),
                headers=[('Content-Type', 'application/json; charset=utf-8')],
            )

        except Exception as e:
            _logger.error("Shopee get_order_detail error: %s", str(e), exc_info=True)
            return request.make_response(
                json.dumps({'error': str(e)}),
                headers=[('Content-Type', 'application/json')],
            )

