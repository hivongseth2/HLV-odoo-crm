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
    def _verify_push_authorization(shop):
        """Verify Shopee's HMAC-SHA256 signature for a Live Push request."""
        authorization = request.httprequest.headers.get('Authorization', '').strip()
        if authorization.lower().startswith('sha256='):
            authorization = authorization.split('=', 1)[1].strip()

        config = request.env['ir.config_parameter'].sudo()
        live_push_partner_key = (
            config.get_param('shopee_webhook.live_push_partner_key') or ''
        ).strip()
        if not authorization or not live_push_partner_key:
            _logger.warning(
                "Shopee Webhook: Missing Authorization header or Live Push Partner "
                "Key for shop %s. Configure system parameter "
                "shopee_webhook.live_push_partner_key.",
                shop.display_name,
            )
            return False

        callback_url = (
            config.get_param('shopee_webhook.callback_url')
            or request.httprequest.url
        ).strip()
        raw_body = request.httprequest.get_data(cache=True)
        base_string = callback_url.encode('utf-8') + b'|' + raw_body
        expected = hmac.new(
            live_push_partner_key.encode('utf-8'),
            base_string,
            hashlib.sha256,
        ).hexdigest()
        is_valid = hmac.compare_digest(expected, authorization.lower())
        if not is_valid:
            _logger.warning(
                "Shopee Webhook: Authorization HMAC mismatch for shop_id=%s; "
                "callback_url=%s, body_bytes=%s, authorization_length=%s.",
                shop.shop_identifier,
                callback_url,
                len(raw_body),
                len(authorization),
            )
        else:
            _logger.info(
                "Shopee Webhook: Authorization verified for shop_id=%s; "
                "callback_url=%s.",
                shop.shop_identifier,
                callback_url,
            )
        return is_valid

    @staticmethod
    def _update_tracking_number(orders, tracking_no, package_number=None):
        """Apply an order_trackingno_push value to related delivery pickings."""
        updated_pickings = request.env['stock.picking'].sudo()
        matched_pickings = request.env['stock.picking'].sudo()

        for order in orders:
            pick_pickings = order.picking_ids.sudo().filtered(
                lambda picking: 'PICK' in (
                    picking.picking_type_id.sequence_code or ''
                ).upper() and picking.state != 'cancel'
            )
            outgoing_pickings = order.picking_ids.sudo().filtered(
                lambda picking: picking.picking_type_code == 'outgoing'
                and picking.state != 'cancel'
            )
            preferred_pickings = pick_pickings or outgoing_pickings
            active_pickings = preferred_pickings.filtered(
                lambda picking: picking.state != 'done'
            )
            candidate_pickings = active_pickings or preferred_pickings
            target_pickings = candidate_pickings.sorted('id')[:1]
            matched_pickings |= target_pickings

            if not target_pickings:
                _logger.warning(
                    "Shopee Webhook: Order %s has no PICK/outgoing picking for tracking number %s.",
                    order.name,
                    tracking_no,
                )
                continue

            if len(candidate_pickings) > 1:
                _logger.warning(
                    "Shopee Webhook: Order %s has %s delivery pickings; applying tracking "
                    "number %s to oldest picking %s (package_number=%s).",
                    order.name,
                    len(candidate_pickings),
                    tracking_no,
                    target_pickings.name,
                    package_number or '',
                )

            changed_pickings = target_pickings.filtered(
                lambda picking: picking.carrier_tracking_ref != tracking_no
                or picking.name != tracking_no
            )
            if changed_pickings:
                old_picking_names = ', '.join(changed_pickings.mapped('name'))
                changed_pickings.write({
                    'carrier_tracking_ref': tracking_no,
                    'name': tracking_no,
                })
                updated_pickings |= changed_pickings
                _logger.info(
                    "Shopee Webhook: Updated order %s pickings %s -> %s "
                    "(package_number=%s).",
                    order.name,
                    old_picking_names,
                    tracking_no,
                    package_number or '',
                )

        return updated_pickings, matched_pickings

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
            # Get JSON data from request
            data = request.get_json_data()
            _logger.info("Received Shopee Webhook Data: %s", json.dumps(data))

            # Ghi vào file log persistent (log trước khi xử lý)
            _log_to_file(data)

            if not data:
                 return self._empty_push_response(status=400)
            
            
            # pass bài test
             
            shopee_data = data.get('data', {})
            if shopee_data and 'verify_info' in shopee_data:
                _logger.info("Shopee Webhook: Processing Verification Message")
                # Trả về đúng format Shopee yêu cầu để pass bài test
                return request.make_json_response({
                    "verify_info": shopee_data['verify_info']
                })

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

            # code=4 is Shopee's documented order_trackingno_push payload.
            package_number = None
            if str(push_code) == '4':
                ordersn = shopee_data.get('ordersn')
                tracking_no = shopee_data.get('tracking_no')
                package_number = shopee_data.get('package_number')
                if not ordersn or not tracking_no:
                    _logger.warning(
                        "Shopee Webhook: Invalid code=4 payload; ordersn=%s tracking_no=%s.",
                        ordersn,
                        tracking_no,
                    )
                    return self._empty_push_response()
            else:
                tracking_no = find_value(data, 'tracking_no') or find_value(data, 'tracking_number')

            if not ordersn and not tracking_no:
                _logger.warning("Shopee Webhook: Could not find 'ordersn' or 'tracking_no' in payload.")
                return self._empty_push_response()

            # Find the Sale Order
            orders = request.env['sale.order'].sudo()
            if ordersn:
                # 1. Try finding by Shopee Order Ref (Mã đơn hàng)
                candidate_orders = request.env['sale.order'].sudo().search(
                    [('shopee_order_ref', '=', ordersn)]
                )
                if str(push_code) == '4':
                    shop_id_raw = data.get('shop_id')
                    shop = request.env['shopee.shop'].sudo().search(
                        [('shop_identifier', '=', str(shop_id_raw))], limit=1
                    ) if shop_id_raw else request.env['shopee.shop'].sudo()
                    if not shop:
                        _logger.warning(
                            "Shopee Webhook: Cannot apply tracking number for order %s; "
                            "shop_id=%s is missing or unknown.",
                            ordersn,
                            shop_id_raw,
                        )
                        return self._empty_push_response(status=500)
                    if not self._verify_push_authorization(shop):
                        _logger.warning(
                            "Shopee Webhook: Invalid push Authorization for shop_id=%s, order=%s.",
                            shop_id_raw,
                            ordersn,
                        )
                        return self._empty_push_response(status=403)
                    same_shop_orders = candidate_orders.filtered(
                        lambda order: order.shopee_shop_id == shop
                    )
                    unassigned_shop_orders = candidate_orders.filtered(
                        lambda order: not order.shopee_shop_id
                    )
                    orders = same_shop_orders or unassigned_shop_orders
                    if candidate_orders and not orders:
                        _logger.warning(
                            "Shopee Webhook: Shop mismatch for order %s; payload shop_id=%s.",
                            ordersn,
                            shop_id_raw,
                        )
                        return self._empty_push_response()
                else:
                    orders = candidate_orders
            
            if str(push_code) != '4' and not orders and tracking_no:
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
                return self._empty_push_response(status=500)

            if str(push_code) == '4':
                updated_pickings, matched_pickings = self._update_tracking_number(
                    orders, tracking_no, package_number=package_number
                )
                if not matched_pickings:
                    _log_to_file(
                        data,
                        result="Tracking %s pending: no delivery picking" % tracking_no,
                    )
                    return self._empty_push_response(status=500)
                result = (
                    "Tracking %s applied to %s"
                    % (tracking_no, ', '.join(updated_pickings.mapped('name')))
                    if updated_pickings
                    else "Tracking %s already current" % tracking_no
                )
                _log_to_file(data, result=result)

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
            return self._empty_push_response(status=500)

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
