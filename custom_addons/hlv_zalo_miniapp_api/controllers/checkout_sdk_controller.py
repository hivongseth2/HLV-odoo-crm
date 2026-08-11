# -*- coding: utf-8 -*-
import hmac
import hashlib
import json
import logging
import time

from odoo import http, fields, _
from odoo.http import request, Response

from .base_api import ZaloBaseAPI

_logger = logging.getLogger(__name__)


class ZaloCheckoutSDKController(ZaloBaseAPI, http.Controller):

    def _get_private_key(self):
        """Lấy Private Key từ hệ thống cấu hình ir.config_parameter."""
        return request.env['ir.config_parameter'].sudo().get_param('hlv_zalo_miniapp.checkout_private_key', '')

    def _get_app_id(self):
        """Lấy Zalo Mini App ID từ cấu hình."""
        return request.env['ir.config_parameter'].sudo().get_param('hlv_zalo_miniapp.checkout_app_id', '')

    def _is_sandbox(self):
        """Kiểm tra môi trường Checkout SDK có bật Sandbox không."""
        val = request.env['ir.config_parameter'].sudo().get_param('hlv_zalo_miniapp.checkout_sandbox_mode', 'True')
        return str(val).lower() in ('true', '1', 'yes')

    def _generate_create_order_mac(self, params, private_key):
        """
        Tính toán chuỗi MAC bảo mật bằng HMAC-SHA256 theo quy tắc Zalo Checkout SDK:
        1. Gom các keys: amount, desc, extradata, item (và method nếu có)
        2. Format extradata và method về JSON String
        3. Format item về String (JSON stringified list)
        4. Sắp xếp các key theo thứ tự từ điển A-Z
        5. Nối chuỗi dạng key=value phân cách bằng &
        6. Tạo mã HMAC-SHA256 với private_key
        """
        if not private_key:
            return ""

        formatted_map = {
            'amount': str(params['amount']),
            'desc': str(params['desc']),
            'extradata': json.dumps(params['extradata'], sort_keys=True, separators=(',', ':')) if isinstance(params['extradata'], (dict, list)) else str(params['extradata']),
            'item': json.dumps(params['item'], separators=(',', ':')) if isinstance(params['item'], (dict, list)) else str(params['item']),
        }

        if 'method' in params and params['method']:
            formatted_map['method'] = json.dumps(params['method'], sort_keys=True, separators=(',', ':')) if isinstance(params['method'], (dict, list)) else str(params['method'])

        sorted_keys = sorted(formatted_map.keys())
        raw_data = "&".join([f"{k}={formatted_map[k]}" for k in sorted_keys])

        mac = hmac.new(
            private_key.encode('utf-8'),
            raw_data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        return mac

    @http.route('/api/v1/zalo_checkout/init_order', type='json', auth='public', methods=['POST'], csrf=False)
    def init_checkout_order(self, **post):
        """
        API khởi tạo đơn hàng thanh toán trên Odoo Backend và tạo chữ ký MAC cho Zalo Checkout SDK.
        Body payload:
        {
            "contact_id": 123,
            "items": [{"product_id": 456, "quantity": 2, "price_unit": 50000}],
            "address_id": 789,
            "note": "Giao giờ hành chính",
            "voucher_code": "VOUCHER10",
            "payment_method": "zalopay" // "zalopay", "vnpay", hoặc "cod"
        }
        """
        try:
            body = self._request_json()
            contact_id = body.get('contact_id')
            items = body.get('items', [])
            address_id = body.get('address_id')
            note = body.get('note', '')
            voucher_code = body.get('voucher_code', '')
            payment_method_input = body.get('payment_method', 'cod').lower()

            if not contact_id or not items:
                return {'status': 'error', 'message': 'Thiếu thông tin contact_id hoặc sản phẩm đơn hàng'}

            partner = request.env['res.partner'].sudo().browse(int(contact_id))
            if not partner.exists():
                return {'status': 'error', 'message': 'Khách hàng không tồn tại'}

            # 1. Map địa chỉ nhận hàng
            addr_domain = [('id', '=', int(address_id))] if address_id else [('id', '=', partner.id)]
            delivery_partner = request.env['res.partner'].sudo().search(addr_domain, limit=1) or partner

            # 2. Chuẩn bị danh sách sản phẩm & tính tổng tiền
            order_lines = []
            sdk_items = []
            total_amount = 0

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
                    'name': product.display_name,
                }))

                sdk_items.append({
                    'id': str(product.id),
                    'amount': line_subtotal,
                })

            if not order_lines:
                return {'status': 'error', 'message': 'Không tìm thấy sản phẩm hợp lệ'}

            # 3. Tạo Sale Order trong Odoo ở trạng thái draft
            order_vals = {
                'partner_id': partner.id,
                'partner_shipping_id': delivery_partner.id,
                'order_line': order_lines,
                'note': note,
                'x_zalo_payment_method': payment_method_input,
                'x_zalo_payment_status': 'pending',
            }

            sale_order = request.env['sale.order'].sudo().create(order_vals)

            # 4. Xác định mã phương thức thanh toán dựa theo môi trường Sandbox / Production
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
                'isCustom': False
            }

            extradata_obj = {
                'odoo_order_id': sale_order.id,
                'odoo_order_name': sale_order.name,
                'contact_id': partner.id
            }

            desc_text = f"Thanh toan don hang {sale_order.name}"

            params_for_mac = {
                'amount': int(sale_order.amount_total or total_amount),
                'desc': desc_text,
                'item': sdk_items,
                'extradata': extradata_obj,
                'method': method_obj
            }

            private_key = self._get_private_key()
            if not private_key:
                _logger.error("CHƯA CẤU HÌNH Private Key cho Zalo Checkout SDK! Vui lòng cài đặt System Parameter 'hlv_zalo_miniapp.checkout_private_key'.")
                return {
                    'status': 'error',
                    'message': 'Odoo Server chưa được cấu hình Private Key cho Zalo Checkout SDK. Vui lòng vào Odoo Settings > System Parameters thêm hlv_zalo_miniapp.checkout_private_key'
                }

            mac_str = self._generate_create_order_mac(params_for_mac, private_key)

            return {
                'status': 'success',
                'data': {
                    'orderId': sale_order.name,
                    'odoo_id': sale_order.id,
                    'amount': int(sale_order.amount_total or total_amount),
                    'desc': desc_text,
                    'item': sdk_items,
                    'extradata': extradata_obj,
                    'method': method_obj,
                    'mac': mac_str,
                }
            }
        except Exception as e:
            _logger.exception("Lỗi khởi tạo đơn hàng Checkout SDK: %s", str(e))
            return {'status': 'error', 'message': f'Lỗi hệ thống: {str(e)}'}

    @http.route('/api/zalo/checkout/callback', type='json', auth='public', methods=['POST'], csrf=False)
    def zalo_checkout_callback(self, **post):
        """
        Webhook nhận kết quả thanh toán từ Zalo Checkout SDK Server.
        Zalo Server sẽ POST payload JSON dạng:
        {
            "data": {
                "appId": "...",
                "orderId": "SO001",
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
                    hashlib.sha256
                ).hexdigest()

                if calc_mac.lower() != req_mac.lower():
                    _logger.warning("Zalo Checkout Callback MAC mismatch! Expected: %s, Received: %s", calc_mac, req_mac)
                    return {'returnCode': -1, 'returnMessage': 'Invalid MAC signature'}

            # 2. Tìm đơn hàng Odoo theo order_id (sale.order.name)
            sale_order = request.env['sale.order'].sudo().search([('name', '=', order_id)], limit=1)
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

    @http.route('/api/zalo/checkout/notify', type='json', auth='public', methods=['POST'], csrf=False)
    def zalo_checkout_notify(self, **post):
        """
        Webhook nhận thông báo khi người dùng chọn phương thức COD hoặc Bank Transfer.
        Payload:
        {
            "data": {
                "appId": "...",
                "orderId": "SO001",
                "method": "COD"
            },
            "mac": "..."
        }
        """
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
                    hashlib.sha256
                ).hexdigest()

                if calc_mac.lower() != req_mac.lower():
                    return {'returnCode': -1, 'returnMessage': 'Invalid MAC signature'}

            sale_order = request.env['sale.order'].sudo().search([('name', '=', order_id)], limit=1)
            if sale_order:
                sale_order.write({
                    'x_zalo_payment_method': method,
                })
                _logger.info("Zalo Checkout Notify: Đơn %s ghi nhận phương thức %s", order_id, method)

            return {'returnCode': 1, 'returnMessage': 'Success'}
        except Exception as e:
            _logger.exception("Lỗi khi xử lý Notify Zalo Checkout: %s", str(e))
            return {'returnCode': -1, 'returnMessage': str(e)}
