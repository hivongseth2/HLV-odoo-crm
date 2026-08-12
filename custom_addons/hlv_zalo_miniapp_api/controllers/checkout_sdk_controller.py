# -*- coding: utf-8 -*-
import hmac
import hashlib
import json
import logging
import time
import uuid

from odoo import http, fields
from odoo.http import request, Response

from .base_api import ZaloBaseAPI

_logger = logging.getLogger(__name__)


class _CheckoutError(Exception):
    """
    Lỗi nghiệp vụ của flow Checkout SDK.
    Được convert thành REST error response trong controller.
    """

    def __init__(self, code, message, status=400):
        super(_CheckoutError, self).__init__(message)
        self.code = code
        self.message = message
        self.status = status


class ZaloCheckoutSDKController(ZaloBaseAPI, http.Controller):

    def _get_private_key(self):
        """Lấy Private Key từ hệ thống cấu hình ir.config_parameter."""
        ICP = request.env['ir.config_parameter'].sudo()
        val = ICP.get_param('hlv_zalo_miniapp.checkout_private_key', '') or ICP.get_param('checkout_private_key', '') or ICP.get_param('zalo.checkout_private_key', '')
        return str(val or '').strip()

    def _get_app_id(self):
        """Lấy Zalo Mini App ID từ cấu hình."""
        val = request.env['ir.config_parameter'].sudo().get_param('hlv_zalo_miniapp.checkout_app_id', '')
        return str(val or '').strip()

    def _is_sandbox(self):
        """Kiểm tra môi trường Checkout SDK có bật Sandbox không."""
        val = request.env['ir.config_parameter'].sudo().get_param('hlv_zalo_miniapp.checkout_sandbox_mode', 'True')
        return str(val).lower() in ('true', '1', 'yes')
    def _generate_create_order_mac(self, params, private_key):
        """
        Quy tắc tính MAC cho createOrder / purchase của Zalo Checkout SDK:
        1. Gom các keys: amount, desc, extradata, item (và method nếu có)
        2. Format extradata và method về JSON String (sắp xếp key từ điển A-Z, separators=(',', ':'))
        3. Format item về String (JSON stringified list với key từng item từ điển A-Z)
        4. Sắp xếp các key ở cấp cao nhất (top-level) theo thứ tự từ điển A-Z
        5. Nối chuỗi dạng key=value phân cách bằng &
        6. Tạo mã HMAC-SHA256 với private_key
        """
        if not private_key:
            return ""

        def _json_serialize(obj):
            if isinstance(obj, (dict, list)):
                return json.dumps(obj, separators=(',', ':'), sort_keys=True, ensure_ascii=False)
            return str(obj)

        formatted_map = {
            'amount': str(params['amount']),
            'desc': str(params['desc']),
            'extradata': _json_serialize(params['extradata']) if isinstance(params['extradata'], (dict, list)) else str(params['extradata']),
            'item': _json_serialize(params['item']) if isinstance(params['item'], (dict, list)) else str(params['item']),
        }

        if 'method' in params and params['method']:
            formatted_map['method'] = _json_serialize(params['method']) if isinstance(params['method'], (dict, list)) else str(params['method'])

        sorted_keys = sorted(formatted_map.keys())
        raw_data = "&".join([f"{k}={formatted_map[k]}" for k in sorted_keys])

        _logger.info("Zalo Checkout MAC raw_data: %s", raw_data)

        mac = hmac.new(
            private_key.encode('utf-8'),
            raw_data.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        return mac



    def _build_checkout_payload(self, body, private_key):
        """
        Build & validate payload thanh toán từ body yêu cầu.
        KHÔNG tạo sale.order ở đây.
        Trả dict payload (amount, desc, sdk_items, mac, ...).
        Raise _CheckoutError nếu dữ liệu không hợp lệ.
        """
        contact_id = body.get('contact_id')
        items = body.get('items', [])
        address_id = body.get('address_id')
        payment_method_input = str(body.get('payment_method', 'cod')).lower()

        if not contact_id or not items:
            raise _CheckoutError("INVALID_INPUT", "Thiếu thông tin contact_id hoặc sản phẩm đơn hàng")

        partner = request.env['res.partner'].sudo().browse(int(contact_id))
        if not partner.exists():
            raise _CheckoutError("NOT_FOUND", "Khách hàng không tồn tại", 404)

        # 1. Map địa chỉ nhận hàng
        addr_domain = [('id', '=', int(address_id))] if address_id else [('id', '=', partner.id)]
        delivery_partner = request.env['res.partner'].sudo().search(addr_domain, limit=1) or partner

        # 2. Chuẩn bị danh sách sản phẩm & tính tổng tiền
        order_lines = []
        sdk_items = []
        total_amount = 0
        item_refs = []

        for it in items:
            product_id = int(it.get('product_id'))
            qty = int(it.get('quantity', 1))
            price = float(it.get('price_unit', 0))

            product = request.env['product.product'].sudo().browse(product_id)
            if not product.exists():
                continue

            if price <= 0:
                price = product.x_zalo_price or product.lst_price or product.list_price

            line_subtotal = round(price * qty)
            total_amount += line_subtotal

            order_lines.append((0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'price_unit': price,
                'tax_id': [(5, 0, 0)],  # Giá Zalo đã bao gồm VAT -> không áp thuế
                'name': product.display_name,
            }))
            sdk_items.append({
                'amount': line_subtotal,
                'id': str(product.id),
            })
            item_refs.append({
                'product_id': product.id,
                'quantity': qty,
                'price_unit': price,
            })

        if not order_lines:
            raise _CheckoutError("INVALID_INPUT", "Không tìm thấy sản phẩm hợp lệ")

        # 3. Xác định mã phương thức thanh toán dựa theo môi trường Sandbox / Production
        is_sandbox = self._is_sandbox()

        method_code = 'COD'
        if payment_method_input == 'zalopay':
            method_code = 'ZALOPAY_SANDBOX' if is_sandbox else 'ZALOPAY'
        elif payment_method_input == 'vnpay':
            method_code = 'VNPAY_SANDBOX' if is_sandbox else 'VNPAY'
        elif payment_method_input == 'cod':
            method_code = 'COD_SANDBOX' if is_sandbox else 'COD'

        method_obj = {
            'id': method_code,
            'isCustom': False,
        }

        # Cấp phát trước mã đơn bán hàng dự kiến (sale.order sequence) để gắn vào Ghi chú & Extradata Zalo SDK
        order_name = request.env['ir.sequence'].sudo().next_by_code('sale.order') or 'S00000'

        extradata_obj = {
            'contact_id': partner.id,
            'odoo_order_name': order_name,
        }

        desc_text = f"Thanh toan don hang {order_name}"
        final_order_amount = int(round(total_amount))

        # 4. Đảm bảo quy tắc Zalo Checkout SDK: sum(item[i].amount) == amount tổng
        sum_sdk_items = sum(it['amount'] for it in sdk_items)
        if sdk_items and sum_sdk_items != final_order_amount:
            diff = final_order_amount - sum_sdk_items
            sdk_items[-1]['amount'] += diff

        # 5. Pre-stringify extradata và method để đảm bảo MAC consistency chuẩn Zalo SDK (alphabetical sort)
        extradata_str = json.dumps(extradata_obj, separators=(',', ':'), sort_keys=True, ensure_ascii=False)
        method_str = json.dumps(method_obj, separators=(',', ':'), sort_keys=True, ensure_ascii=False)

        params_for_mac = {
            'amount': final_order_amount,
            'desc': desc_text,
            'item': sdk_items,
            'extradata': extradata_str,
            'method': method_str,
        }

        mac_str = self._generate_create_order_mac(params_for_mac, private_key)
        _logger.info("Zalo Checkout MAC computed: %s (amount=%s, order_name=%s)", mac_str, final_order_amount, order_name)

        return {
            'partner_id': partner.id,
            'delivery_partner_id': delivery_partner.id,
            'address_id': address_id,
            'note': body.get('note', ''),
            'payment_method': payment_method_input,
            'items_json': json.dumps(item_refs),
            'amount': final_order_amount,
            'desc': desc_text,
            'order_name': order_name,
            'sdk_items': sdk_items,
            'item_sdk_json': json.dumps(sdk_items, separators=(',', ':')),
            'extradata_str': extradata_str,
            'method_str': method_str,
            'mac': mac_str,
        }

        return mac

    @http.route('/api/v1/zalo_checkout/prepare', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def prepare_checkout_order(self, **post):
        """
        Bước 1 - CHUẨN BỊ: kiểm tra cấu hình, tính MAC nhưng KHÔNG tạo sale.order.
        Chỉ khi Zalo Checkout SDK (createOrder) thông qua thì frontend gọi /confirm để tạo đơn.

        Body payload:
        {
            "contact_id": 123,
            "items": [{"product_id": 456, "quantity": 2, "price_unit": 50000}],
            "address_id": 789,
            "note": "Giao giờ hành chính",
            "payment_method": "zalopay"
        }
        """
        if request.httprequest.method == 'OPTIONS':
            return self._response_options()
        try:
            body = self._request_json()
            contact_id = body.get('contact_id')
            if not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id")

            auth_result = self._auth_and_verify_owner(int(contact_id))
            if isinstance(auth_result, Response):
                return auth_result

            # Kiểm tra cấu hình TRƯỚC khi xử lý => không tạo ra bản ghi/đơn thừa
            private_key = self._get_private_key()
            if not private_key:
                _logger.error("CHƯA CẤU HÌNH Private Key cho Zalo Checkout SDK! Vui lòng cài đặt System Parameter 'hlv_zalo_miniapp.checkout_private_key'.")
                return self._response_error(
                    "CONFIG_ERROR",
                    "Odoo Server chưa được cấu hình Private Key cho Zalo Checkout SDK. Vui lòng vào Odoo Settings > System Parameters thêm hlv_zalo_miniapp.checkout_private_key.",
                    503,
                )
            if not self._get_app_id():
                _logger.error("CHƯA CẤU HÌNH Zalo App ID cho Checkout SDK! Vui lòng cài đặt System Parameter 'hlv_zalo_miniapp.checkout_app_id'.")
                return self._response_error(
                    "CONFIG_ERROR",
                    "Odoo Server chưa được cấu hình Zalo App ID cho Checkout SDK. Vui lòng vào Odoo Settings > System Parameters thêm hlv_zalo_miniapp.checkout_app_id.",
                    503,
                )

            payload = self._build_checkout_payload(body, private_key)

            token = uuid.uuid4().hex
            request.env['zalo.miniapp.checkout.prepare'].sudo().create({
                'token': token,
                'order_name': payload['order_name'],
                'partner_id': payload['partner_id'],
                'items': payload['items_json'],
                'address_id': payload['address_id'] or 0,
                'note': payload['note'],
                'payment_method': payload['payment_method'],
                'amount': payload['amount'],
                'desc': payload['desc'],
                'item_sdk': payload['item_sdk_json'],
                'extradata_str': payload['extradata_str'],
                'method_str': payload['method_str'],
                'mac': payload['mac'],
            })

            return self._response_success({
                'prepareToken': token,
                'mac': payload['mac'],
                'amount': payload['amount'],
                'desc': payload['desc'],
                'item': payload['sdk_items'],
                'extradata': payload['extradata_str'],
                'method': payload['method_str'],
            })
        except _CheckoutError as e:
            return self._response_error(e.code, e.message, e.status)
        except Exception as e:
            _logger.exception("Lỗi chuẩn bị đơn hàng Checkout SDK: %s", str(e))
            return self._response_error("SERVER_ERROR", f"Lỗi hệ thống: {str(e)}", 500)

    @http.route('/api/v1/zalo_checkout/confirm', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def confirm_checkout_order(self, **post):
        """
        Bước 2 - XÁC NHẬN: chỉ gọi sau khi Zalo Checkout SDK.createOrder thành công.
        Tại đây mới tạo duy nhất 1 sale.order trên Odoo.

        Body:
        {
            "prepare_token": "<prepareToken từ /prepare>",
            "zalo_order_id": "<orderId Zalo trả về trong createOrder>"
        }
        """
        if request.httprequest.method == 'OPTIONS':
            return self._response_options()
        try:
            body = self._request_json()
            prepare_token = (body.get('prepare_token') or body.get('prepareToken') or '').strip()
            zalo_order_id = (body.get('zalo_order_id') or '').strip()
            if not prepare_token or not zalo_order_id:
                return self._response_error("INVALID_INPUT", "Thiếu prepare_token hoặc zalo_order_id")

            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result
            token_partner_id = auth_result

            Prepare = request.env['zalo.miniapp.checkout.prepare'].sudo()
            prepare = Prepare.search([('token', '=', prepare_token)], limit=1)
            if not prepare or prepare.consumed:
                return self._response_error("INVALID_STATE", "Token chuẩn bị không hợp lệ hoặc đã được sử dụng", 400)
            if prepare.partner_id.id != token_partner_id:
                return self._response_error("FORBIDDEN", "Không có quyền xác nhận đơn hàng này", 403)

            # Rebuild order lines từ items đã được chuẩn bị (chống client bịa số tiền)
            items = json.loads(prepare.items or '[]')
            order_lines = []
            for it in items:
                product_id = int(it.get('product_id'))
                qty = it.get('quantity', 1)
                price_unit = float(it.get('price_unit', 0))
                product = request.env['product.product'].sudo().browse(product_id)
                if not product.exists():
                    continue
                if price_unit <= 0:
                    price_unit = product.x_zalo_price or product.lst_price or product.list_price
                order_lines.append((0, 0, {
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'price_unit': price_unit,
                    'tax_id': [(5, 0, 0)],
                    'name': product.display_name,
                }))

            if not order_lines:
                return self._response_error("INVALID_INPUT", "Không có sản phẩm hợp lệ để tạo đơn")

            delivery_partner = prepare.partner_id
            if prepare.address_id:
                addr = request.env['res.partner'].sudo().browse(int(prepare.address_id))
                if addr.exists():
                    delivery_partner = addr

            # Gán pricelist như flow order_api để tránh thiếu field bắt buộc khi tạo sale.order
            pricelist_id = False
            try:
                pricelist = request.env["product.pricelist"].sudo().search([("active", "=", True)], limit=1, order="id")
                if pricelist:
                    pricelist_id = pricelist.id
            except Exception:
                pass

            order_vals = {
                'name': prepare.order_name or request.env['ir.sequence'].sudo().next_by_code('sale.order'),
                'partner_id': prepare.partner_id.id,
                'partner_shipping_id': delivery_partner.id,
                'order_line': order_lines,
                'note': prepare.note or '',
                'x_zalo_payment_method': prepare.payment_method,
                'x_zalo_payment_status': 'pending',
                'x_zalo_order_id': zalo_order_id,
            }
            if pricelist_id:
                order_vals['pricelist_id'] = pricelist_id

            sale_order = request.env['sale.order'].sudo().create(order_vals)

            prepare.write({'consumed': True})

            return self._response_success({
                'orderId': zalo_order_id,
                'odoo_id': sale_order.id,
                'order_name': sale_order.name,
                'amount': prepare.amount,
                'status': 'pending',
            })
        except Exception as e:
            _logger.exception("Lỗi xác nhận đơn hàng Checkout SDK: %s", str(e))
            return self._response_error("SERVER_ERROR", f"Lỗi hệ thống: {str(e)}", 500)

    @http.route('/api/zalo/checkout/callback', type='json', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def zalo_checkout_callback(self, **post):
        """
        Webhook nhận kết quả thanh toán từ Zalo Checkout SDK Server.
        Zalo Server sẽ POST payload JSON dạng:
        {
            "data": {
                "appId": "...",
                "orderId": "...",
                "transId": "TRANS123",
                "method": "ZALOPAY_SANDBOX",
                "transTime": 1710832784000,
                "amount": 50000,
                "description": "...",
                "resultCode": 1,
                "message": "Payment successful"
            },
            "mac": "...",
            "overallMac": "..."
        }
        """
        if request.httprequest.method == 'OPTIONS':
            return self._response_options()
        try:
            body = self._request_json()
            data = body.get('data', {})
            req_mac = body.get('mac', '')
            req_overall_mac = body.get('overallMac', '')

            if not data:
                return {'returnCode': -1, 'returnMessage': 'Missing data payload'}

            app_id = str(data.get('appId', ''))
            order_id = str(data.get('orderId', ''))
            trans_id = str(data.get('transId', ''))
            amount = data.get('amount')
            description = str(data.get('description', ''))
            result_code = data.get('resultCode')
            message = str(data.get('message', ''))
            method = str(data.get('method', ''))

            private_key = self._get_private_key()

            # 1. Kiểm tra chữ ký MAC
            # Formula: appId={appId}&amount={amount}&description={description}&orderId={orderId}&message={message}&resultCode={resultCode}&transId={transId}
            if private_key:
                raw_mac_str = f"appId={app_id}&amount={amount}&description={description}&orderId={order_id}&message={message}&resultCode={result_code}&transId={trans_id}"
                calc_mac = hmac.new(
                    private_key.encode('utf-8'),
                    raw_mac_str.encode('utf-8'),
                    hashlib.sha256,
                ).hexdigest()

                if calc_mac.lower() != req_mac.lower():
                    _logger.warning("Zalo Checkout Callback MAC mismatch! Expected: %s, Received: %s", calc_mac, req_mac)
                    return {'returnCode': -1, 'returnMessage': 'Invalid MAC signature'}

            # 2. Tìm đơn hàng Odoo theo zalo_order_id (fallback theo sale.order.name cho dữ liệu cũ)
            SaleOrder = request.env['sale.order'].sudo()
            sale_order = SaleOrder.search([('x_zalo_order_id', '=', order_id)], limit=1) or SaleOrder.search([('name', '=', order_id)], limit=1)
            if not sale_order:
                _logger.warning("Zalo Checkout Callback: Sale Order %s không tồn tại", order_id)
                return {'returnCode': -1, 'returnMessage': 'Order not found'}

            # 3. Kiểm tra tính trùng lặp đơn hàng đã thanh toán thành công trước đó
            if sale_order.x_zalo_payment_status == 'paid':
                _logger.info("Zalo Checkout Callback: Order %s đã thanh toán trước đó", order_id)
                return {'returnCode': 2, 'returnMessage': 'Order already processed'}

            # 4. Xử lý cập nhật trạng thái đơn hàng
            if result_code == 1:
                # Thanh toán thành công -> Xác nhận đơn hàng & Cập nhật trạng thái
                try:
                    if sale_order.state == 'draft':
                        sale_order.action_confirm()
                except Exception as cf_err:
                    _logger.warning("Không thể tự động action_confirm cho %s: %s", order_id, str(cf_err))

                sale_order.write({
                    'x_zalo_payment_status': 'paid',
                    'x_zalo_trans_id': trans_id,
                    'x_zalo_payment_method': method,
                    'x_zalo_trans_time': fields.Datetime.now(),
                })
                _logger.info("Zalo Checkout Callback THÀNH CÔNG cho đơn hàng %s (TransID: %s)", order_id, trans_id)
                return {'returnCode': 1, 'returnMessage': 'Success'}
            else:
                # Thanh toán thất bại
                sale_order.write({
                    'x_zalo_payment_status': 'failed',
                    'x_zalo_trans_id': trans_id,
                    'x_zalo_payment_method': method,
                })
                _logger.warning("Zalo Checkout Callback THẤT BẠI cho đơn hàng %s: %s", order_id, message)
                return {'returnCode': 1, 'returnMessage': 'Failure recorded'}

        except Exception as e:
            _logger.exception("Lỗi khi xử lý Callback Zalo Checkout SDK: %s", str(e))
            return {'returnCode': -1, 'returnMessage': f'Internal Server Error: {str(e)}'}
    @http.route('/api/zalo/checkout/notify', type='json', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def zalo_checkout_notify(self, **post):
        """
        Webhook nhận thông báo khi người dùng chọn phương thức COD hoặc Bank Transfer.
        Payload:
        {
            "data": {
                "appId": "...",
                "orderId": "...",
                "method": "COD"
            },
            "mac": "..."
        }
        """
        if request.httprequest.method == 'OPTIONS':
            return self._response_options()
        try:
            body = self._request_json()
            data = body.get('data', {})
            req_mac = body.get('mac', '')

            app_id = str(data.get('appId', ''))
            order_id = str(data.get('orderId', ''))
            method = str(data.get('method', ''))

            private_key = self._get_private_key()

            # Verify MAC: appId={appId}&orderId={orderId}&method={method}
            if private_key:
                raw_mac = f"appId={app_id}&orderId={order_id}&method={method}"
                calc_mac = hmac.new(
                    private_key.encode('utf-8'),
                    raw_mac.encode('utf-8'),
                    hashlib.sha256,
                ).hexdigest()

                if calc_mac.lower() != req_mac.lower():
                    return {'returnCode': -1, 'returnMessage': 'Invalid MAC signature'}

            SaleOrder = request.env['sale.order'].sudo()
            sale_order = SaleOrder.search([('x_zalo_order_id', '=', order_id)], limit=1) or SaleOrder.search([('name', '=', order_id)], limit=1)
            if sale_order:
                sale_order.write({
                    'x_zalo_payment_method': method,
                })
                _logger.info("Zalo Checkout Notify: Đơn %s ghi nhận phương thức %s", order_id, method)

            return {'returnCode': 1, 'returnMessage': 'Success'}
        except Exception as e:
            _logger.exception("Lỗi khi xử lý Notify Zalo Checkout: %s", str(e))
            return {'returnCode': -1, 'returnMessage': str(e)}

    @http.route('/api/v1/zalo_checkout/get_status', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def query_zalo_order_status(self, **post):
        """
        API Server-to-Server chủ động tra cứu trạng thái giao dịch từ Zalo Checkout SDK Server.
        Endpoint: POST https://payment-mini.zalo.me/api/transaction/get-status

        Body:
        {
            "zalo_order_id": "154153230724310053847738335_1786506836347"
        }
        """
        if request.httprequest.method == 'OPTIONS':
            return self._response_options()
        try:
            import requests

            body = self._request_json()
            order_id = (body.get('zalo_order_id') or body.get('orderId') or '').strip()
            if not order_id:
                return self._response_error("INVALID_INPUT", "Thiếu zalo_order_id")

            app_id = self._get_app_id()
            private_key = self._get_private_key()

            if not app_id or not private_key:
                return self._response_error("CONFIG_ERROR", "Chưa cấu hình Zalo App ID hoặc Private Key")

            # MAC formula: appId={appId}&orderId={orderId}&privateKey={privateKey}
            raw_mac = f"appId={app_id}&orderId={order_id}&privateKey={private_key}"
            mac = hmac.new(
                private_key.encode('utf-8'),
                raw_mac.encode('utf-8'),
                hashlib.sha256,
            ).hexdigest()

            target_url = "https://payment-mini.zalo.me/api/transaction/get-status"
            params = {
                "appId": app_id,
                "orderId": order_id,
                "mac": mac,
            }
            headers = {"Content-Type": "application/json"}

            _logger.info("Gọi Zalo getOrderStatus (GET) cho orderId=%s...", order_id)
            resp = requests.get(target_url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200 or not resp.text or not resp.text.strip():
                resp = requests.post(target_url, json=params, headers=headers, timeout=10)

            res_data = {}
            if resp.text and resp.text.strip():
                try:
                    res_data = resp.json()
                except Exception:
                    res_data = {"raw_text": resp.text}

            _logger.info("Zalo getOrderStatus Response: HTTP %s - Body: %s", resp.status_code, resp.text)

            return self._response_success({
                "status_code": resp.status_code,
                "zalo_response": res_data,
            })
        except Exception as e:
            _logger.exception("Lỗi tra cứu trạng thái giao dịch Zalo: %s", str(e))
            return self._response_error("SERVER_ERROR", f"Lỗi hệ thống: {str(e)}", 500)

    @http.route('/api/zalo/checkout/vnpay_ipn', type='json', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def zalo_checkout_vnpay_ipn(self, **post):
        """
        Webhook IPN riêng nhận thông báo giao dịch VNPay tích hợp qua Zalo Checkout SDK.
        """
        if request.httprequest.method == 'OPTIONS':
            return self._response_options()
        try:
            body = self._request_json()
            data = body.get('data', {})
            order_id = str(data.get('orderId', ''))
            vnp_response_code = str(data.get('vnp_ResponseCode', data.get('resultCode', '')))
            trans_id = str(data.get('transId', data.get('vnp_TransactionNo', '')))

            _logger.info("Nhận VNPay IPN Webhook cho orderId=%s (vnp_ResponseCode=%s)", order_id, vnp_response_code)

            if not order_id:
                return {'RspCode': '99', 'Message': 'Invalid OrderId'}

            SaleOrder = request.env['sale.order'].sudo()
            sale_order = SaleOrder.search([('x_zalo_order_id', '=', order_id)], limit=1) or SaleOrder.search([('name', '=', order_id)], limit=1)

            if not sale_order:
                return {'RspCode': '01', 'Message': 'Order not found'}

            if sale_order.x_zalo_payment_status == 'paid':
                return {'RspCode': '02', 'Message': 'Order already confirmed'}

            if vnp_response_code in ('00', '1'):
                try:
                    if sale_order.state == 'draft':
                        sale_order.action_confirm()
                except Exception:
                    pass

                sale_order.write({
                    'x_zalo_payment_status': 'paid',
                    'x_zalo_trans_id': trans_id,
                    'x_zalo_payment_method': 'VNPAY',
                    'x_zalo_trans_time': fields.Datetime.now(),
                })
                return {'RspCode': '00', 'Message': 'Confirm Success'}
            else:
                sale_order.write({
                    'x_zalo_payment_status': 'failed',
                    'x_zalo_trans_id': trans_id,
                    'x_zalo_payment_method': 'VNPAY',
                })
                return {'RspCode': '00', 'Message': 'Transaction Failed Recorded'}
        except Exception as e:
            _logger.exception("Lỗi khi xử lý VNPay IPN Webhook: %s", str(e))
            return {'RspCode': '99', 'Message': f'Uncertain Error: {str(e)}'}



