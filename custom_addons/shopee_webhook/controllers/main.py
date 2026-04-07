# -*- coding: utf-8 -*-
import json
import os
import logging
from datetime import datetime
from odoo import http
from odoo.http import request
from odoo.addons.shopee_order_fetch.services import shopee_api, shopee_order_builder, shopee_escrow

_logger = logging.getLogger(__name__)

# Use a writable directory outside the module path, typically in the user's home or tmp
try:
    _LOG_DIR = os.path.join(os.path.expanduser('~'), 'shopee_logs')
    os.makedirs(_LOG_DIR, exist_ok=True)
except Exception:
    # Fallback to /tmp if home dir is not writable
    _LOG_DIR = '/tmp/shopee_logs'
    os.makedirs(_LOG_DIR, exist_ok=True)

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

            # Thêm logic mapping tiếng Việt đối với push mechanism code 3 theo yêu cầu
            push_code = data.get('code')
            if str(push_code) == '3' and status:
                status_mapping = {
                    'UNPAID': 'Chưa thanh toán',
                    'READY_TO_SHIP': 'Chờ lấy hàng',
                    'PROCESSED': 'Đã xử lý',
                    'SHIPPED': 'Đang giao',
                    'COMPLETED': 'Hoàn thành',
                    'IN_CANCEL': 'Chờ xác nhận hủy',
                    'CANCELLED': 'Đã hủy',
                    'RETRY_SHIP': 'Giao lại',
                    'TO_CONFIRM_RECEIVE': 'Đã nhận hàng',
                    'TO_RETURN': 'Đang trả hàng'
                }
                status = status_mapping.get(str(status).upper(), status)

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

            if not orders and ordersn:
                # 3. IF ORDER STILL NOT FOUND: AUTO-FETCH FROM SHOPEE
                _logger.info("Shopee Webhook: Order %s not found. Attempting auto-fetch...", ordersn)
                shop_id_raw = data.get('shop_id')
                if not shop_id_raw:
                    _logger.warning("Shopee Webhook: missing shop_id in payload, cannot auto-fetch.")
                else:
                    shop = request.env['shopee.shop'].sudo().search([('shop_identifier', '=', str(shop_id_raw))], limit=1)
                    if not shop:
                        _logger.warning("Shopee Webhook: Shop ID %s not found in Odoo.", shop_id_raw)
                    else:
                        try:
                            # Use services from shopee_order_fetch to pull full details
                            creds = shopee_api.get_credentials_from_shop(shop)
                            
                            # Get full order detail
                            status_code, body, _params = shopee_api.call_order_detail(creds, ordersn)
                            if status_code == 200 and not body.get('error'):
                                order_list = body.get('response', {}).get('order_list', [])
                                if order_list:
                                    order_data = order_list[0]
                                    # Get escrow detail (pricing/vouchers)
                                    escrow_data = shopee_api.call_escrow_detail(creds, ordersn)
                                    
                                    # Build/Create order
                                    with request.env.cr.savepoint():
                                        new_so = shopee_order_builder.create_order_from_data(
                                            request.env, order_data, shop, escrow_data=escrow_data
                                        )
                                        orders = new_so
                                        _logger.info("Shopee Webhook: Auto-fetched successfully: Order %s -> %s", ordersn, new_so.name)
                                        _log_to_file(data, result=f"Auto-fetched order {ordersn}: Created {new_so.name}")
                        except Exception as fetch_err:
                            _logger.error("Shopee Webhook: Auto-fetch failed for %s: %s", ordersn, str(fetch_err))

            if not orders:
                _logger.warning("Shopee Webhook: Order not found for identifier: %s / %s", ordersn, tracking_no)
                return {'code': 0, 'msg': 'Order not found, even after auto-fetch attempt'}

            for order in orders:
                if status:
                    old_status = order.shopee_order_status
                    order.write({'shopee_order_status': status})
                    _logger.info("Shopee Webhook: Updated Order %s status from '%s' to '%s'", order.name, old_status, status)
                    _log_to_file(data, result=f"Updated {order.name}: {old_status} -> {status}")
                else:
                    _logger.info("Shopee Webhook: No status update found in payload for Order %s", order.name)

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
