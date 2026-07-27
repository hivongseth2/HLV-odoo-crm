# -*- coding: utf-8 -*-
import hashlib
import hmac
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

    @staticmethod
    def _empty_push_response(status=204):
        return request.make_response('', status=status)

    @staticmethod
    def _verify_push_authorization(shop, raw_body):
        """Verify Shopee's HMAC-SHA256 Authorization header against the raw body."""
        authorization = request.httprequest.headers.get('Authorization', '').strip()
        partner_key = getattr(shop.account_id.sudo(), 'partner_key', False)
        if not authorization or not partner_key:
            _logger.warning(
                "Shopee Webhook: Missing Authorization header or partner_key for shop %s.",
                shop.display_name,
            )
            return False

        if authorization.lower().startswith('sha256='):
            authorization = authorization.split('=', 1)[1].strip()
        authorization = authorization.lower()

        http_request = request.httprequest
        path = http_request.full_path
        if path.endswith('?'):
            path = path[:-1]

        candidates = []

        def add_candidate(source, url):
            normalized = str(url or '').strip()
            if normalized and normalized not in [item[1] for item in candidates]:
                candidates.append((source, normalized))

        Config = request.env['ir.config_parameter'].sudo()
        add_candidate(
            'shopee_webhook.callback_url',
            Config.get_param('shopee_webhook.callback_url'),
        )

        forwarded_proto = (
            http_request.headers.get('X-Forwarded-Proto', '').split(',', 1)[0].strip()
        )
        forwarded_host = (
            http_request.headers.get('X-Forwarded-Host', '').split(',', 1)[0].strip()
        )
        if forwarded_proto and forwarded_host:
            add_candidate(
                'forwarded',
                '%s://%s%s' % (forwarded_proto, forwarded_host, path),
            )

        web_base_url = Config.get_param('web.base.url')
        if web_base_url:
            add_candidate('web.base.url', web_base_url.rstrip('/') + path)

        add_candidate('request.url', http_request.url)
        if http_request.host:
            # Odoo.sh terminates TLS at the reverse proxy. If proxy_mode is not
            # reflected in the request URL, Shopee still signs the public HTTPS URL.
            add_candidate('request.host+https', 'https://%s%s' % (http_request.host, path))

        for source, callback_url in candidates:
            base_string = '%s|%s' % (callback_url, raw_body)
            expected = hmac.new(
                str(partner_key).encode('utf-8'),
                base_string.encode('utf-8'),
                hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(expected, authorization):
                _logger.info(
                    'Shopee Webhook: Authorization matched callback source=%s url=%s.',
                    source,
                    callback_url,
                )
                return True

        _logger.warning(
            'Shopee Webhook: Authorization mismatch for shop=%s; '
            'callback candidates=%s raw_body_bytes=%s auth_length=%s.',
            shop.display_name,
            [url for _source, url in candidates],
            len(raw_body.encode('utf-8')),
            len(authorization),
        )
        return False

    def _ack_and_enqueue_tracking_push(self, data, raw_body):
        """Persist code=4 quickly and always ACK Shopee with HTTP 204."""
        shopee_data = data.get('data') or {}
        order_sn = shopee_data.get('ordersn')
        tracking_no = shopee_data.get('tracking_no')
        shop_id_raw = data.get('shop_id')

        if not order_sn or not tracking_no or not shop_id_raw:
            result = (
                'ACK 204, ignored invalid code=4 payload: '
                'ordersn=%s tracking_no=%s shop_id=%s'
                % (order_sn, tracking_no, shop_id_raw)
            )
            _logger.warning('Shopee Webhook: %s', result)
            _log_to_file(data, result=result)
            return self._empty_push_response()

        shop = request.env['shopee.shop'].sudo().search(
            [('shop_identifier', '=', str(shop_id_raw))],
            limit=1,
        )
        if not shop:
            result = (
                'ACK 204, ignored code=4: unknown shop_id=%s order=%s'
                % (shop_id_raw, order_sn)
            )
            _logger.warning('Shopee Webhook: %s', result)
            _log_to_file(data, result=result)
            return self._empty_push_response()

        if not self._verify_push_authorization(shop, raw_body):
            result = (
                'ACK 204, rejected code=4: invalid Authorization '
                'shop_id=%s order=%s'
                % (shop_id_raw, order_sn)
            )
            _logger.warning('Shopee Webhook: %s', result)
            _log_to_file(data, result=result)
            return self._empty_push_response()

        try:
            event = request.env['shopee.webhook.event'].sudo().enqueue_tracking_push(
                data
            )
            result = 'ACK 204, queued event=%s tracking=%s' % (
                event.id,
                tracking_no,
            )
            _logger.info('Shopee Webhook: %s', result)
            _log_to_file(data, result=result)
        except Exception as exc:
            # Never make Shopee retry/block pushes because the internal queue
            # is temporarily unavailable. The exception remains in Odoo logs.
            result = 'ACK 204, queue ERROR: %s' % str(exc)
            _logger.exception(
                'Shopee Webhook: failed to queue code=4 order=%s',
                order_sn,
            )
            _log_to_file(data, result=result)
        return self._empty_push_response()

    @http.route('/shopee/webhook/delivery', type='http', auth='public', methods=['POST'], csrf=False)
    def shopee_delivery_webhook(self, **kwargs):
        """
        Endpoint to receive Shopee delivery status updates.
        Shopee Push Mechanism payload format:
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
            # Preserve the exact body for Shopee's HMAC verification.
            raw_body = request.httprequest.get_data(cache=True, as_text=True)
            data = json.loads(raw_body) if raw_body else {}
            _logger.info("Received Shopee Webhook Data: %s", json.dumps(data))

            # Ghi vào file log persistent (log trước khi xử lý)
            _log_to_file(data)

            if not data:
                 return self._empty_push_response()
            
            
            # pass bài test
             
            shopee_data = data.get('data', {})
            if shopee_data and 'verify_info' in shopee_data:
                _logger.info("Shopee Webhook: Processing Verification Message")
                # Trả về đúng format Shopee yêu cầu để pass bài test
                return request.make_json_response({
                    "verify_info": shopee_data['verify_info']
                })

            push_code = data.get('code')
            if str(push_code) == '4':
                return self._ack_and_enqueue_tracking_push(data, raw_body)

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

            tracking_no = (
                find_value(data, 'tracking_no')
                or find_value(data, 'tracking_number')
            )

            if not ordersn and not tracking_no:
                _logger.warning("Shopee Webhook: Could not find 'ordersn' or 'tracking_no' in payload.")
                return self._empty_push_response()

            # Find the Sale Order
            orders = request.env['sale.order'].sudo()
            if ordersn:
                # 1. Try finding by Shopee Order Ref (Mã đơn hàng)
                orders = request.env['sale.order'].sudo().search(
                    [('shopee_order_ref', '=', ordersn)]
                )
            
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
                            # Get full order detail
                            status_code, body, _params, creds = shopee_api.call_order_detail_with_token_refresh(
                                shop, ordersn
                            )
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
                return self._empty_push_response()

            for order in orders:
                if status:
                    old_status = order.shopee_order_status
                    order.write({'shopee_order_status': status})
                    _logger.info("Shopee Webhook: Updated Order %s status from '%s' to '%s'", order.name, old_status, status)
                    _log_to_file(data, result=f"Updated {order.name}: {old_status} -> {status}")

                    # Auto-cancel order when Shopee status is CANCELLED (code 3)
                    if str(push_code) == '3' and status in ['CANCELLED', 'Đã hủy', 'Đã Hủy']:
                        if order.state not in ('cancel', 'done'):
                            if order.delivery_status == 'full':
                                _logger.warning(
                                    "Shopee Webhook: BLOCKED auto-cancel for Order %s — delivery_status=full (đã giao hết).",
                                    order.name,
                                )
                                _log_to_file(data, result=f"BLOCKED cancel {order.name}: delivery_status=full")
                            else:
                                try:
                                    order._action_cancel()
                                    _logger.info("Shopee Webhook: Auto-cancelled Order %s due to Shopee CANCELLED status", order.name)
                                    _log_to_file(data, result=f"Auto-cancelled {order.name}")
                                except Exception as cancel_err:
                                    _logger.error("Shopee Webhook: Failed to cancel Order %s: %s", order.name, str(cancel_err))
                                    _log_to_file(data, result=f"Cancel FAILED for {order.name}: {str(cancel_err)}")
                else:
                    _logger.info("Shopee Webhook: No status update found in payload for Order %s", order.name)

            return self._empty_push_response()

        except Exception as e:
            _logger.error("Error processing Shopee Webhook: %s", str(e), exc_info=True)
            _log_to_file(data if 'data' in dir() else {}, result=f"ERROR: {str(e)}")
            # ACK malformed/unexpected pushes as well so Shopee does not disable
            # the callback because of an internal Odoo failure.
            return self._empty_push_response()

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
