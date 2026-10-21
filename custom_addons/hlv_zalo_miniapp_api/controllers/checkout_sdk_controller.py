# -*- coding: utf-8 -*-
import hmac
import hashlib
import json
import logging
import re
import uuid
from markupsafe import Markup

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
        payment_method_raw = body.get('payment_method')
        payment_method_input = str(payment_method_raw).lower() if payment_method_raw else ""

        if not contact_id or not items:
            raise _CheckoutError("INVALID_INPUT", "Thiếu thông tin contact_id hoặc sản phẩm đơn hàng")

        partner = request.env['res.partner'].sudo().browse(int(contact_id))
        if not partner.exists():
            raise _CheckoutError("NOT_FOUND", "Khách hàng không tồn tại", 404)

        # 1. Map địa chỉ nhận hàng (chỉ địa chỉ của chính khách)
        delivery_partner = self._owned_address(partner, address_id)
        if not delivery_partner:
            raise _CheckoutError("FORBIDDEN", "Địa chỉ giao hàng không hợp lệ", 403)

        # 2. Chuẩn bị danh sách sản phẩm & tính tổng tiền.
        # Giá tính ở server; price_unit client gửi bị bỏ qua. Số lượng <= 0 bị
        # từ chối: một dòng âm từng kéo tổng tiền (và MAC Zalo) xuống tuỳ ý.
        pricelist = self._zalo_pricelist()
        order_lines = []
        sdk_items = []
        total_amount = 0
        item_refs = []

        for it in items:
            product_id = self._parse_int(it.get('product_id'), 0)
            qty = self._parse_int(it.get('quantity'), 0)
            if qty <= 0:
                raise _CheckoutError("INVALID_INPUT", "Số lượng sản phẩm không hợp lệ")

            product = request.env['product.product'].sudo().browse(product_id)
            if not product.exists() or not product.active or not product.x_active_zalo:
                continue

            price = self._zalo_unit_price(product, pricelist)
            if price <= 0:
                raise _CheckoutError("NO_PRICE", f"Sản phẩm '{product.display_name}' chưa có giá, vui lòng liên hệ")

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

        # 3. Xác định mã phương thức thanh toán (Nếu người dùng chọn trước PTTT)
        method_str = None
        if payment_method_input and payment_method_input not in ('none', 'native', 'false'):
            is_sandbox = self._is_sandbox()
            method_input_upper = payment_method_input.upper()
            if is_sandbox and not method_input_upper.endswith('_SANDBOX'):
                method_code = f"{method_input_upper}_SANDBOX"
            else:
                method_code = method_input_upper

            method_obj = {
                'id': method_code,
                'isCustom': False,
            }
            method_str = json.dumps(method_obj, separators=(',', ':'), sort_keys=True, ensure_ascii=False)

        # Cấp phát trước mã đơn bán hàng dự kiến (sale.order sequence) để gắn vào Ghi chú & Extradata Zalo SDK
        order_name = request.env['ir.sequence'].sudo().next_by_code('sale.order') or 'S00000'

        # 3.1. Xác thực và tính toán giảm giá Voucher (nếu có)
        voucher_code = (body.get('voucher_code') or '').strip()
        discount_amount = 0.0
        if voucher_code:
            voucher_res = self._verify_voucher_code(voucher_code, partner.id, total_amount)
            if voucher_res.get('valid'):
                discount_amount = float(voucher_res.get('estimated_discount', 0))
            else:
                _logger.warning("Prepare checkout invalid voucher %s: %s", voucher_code, voucher_res.get('error'))
                voucher_code = ''

        extradata_obj = {
            'contact_id': partner.id,
            'odoo_order_name': order_name,
        }

        desc_text = f"Thanh toan don hang {order_name}"
        final_order_amount = max(int(round(total_amount - discount_amount)), 0)

        # 4. Đảm bảo quy tắc Zalo Checkout SDK: sum(item[i].amount) == amount tổng
        sum_sdk_items = sum(it['amount'] for it in sdk_items)
        if sdk_items and sum_sdk_items != final_order_amount:
            diff = final_order_amount - sum_sdk_items
            sdk_items[-1]['amount'] = max(sdk_items[-1]['amount'] + diff, 0)

        # 5. Pre-stringify extradata và method để đảm bảo MAC consistency chuẩn Zalo SDK (alphabetical sort)
        extradata_str = json.dumps(extradata_obj, separators=(',', ':'), sort_keys=True, ensure_ascii=False)

        params_for_mac = {
            'amount': final_order_amount,
            'desc': desc_text,
            'item': sdk_items,
            'extradata': extradata_str,
        }
        if method_str:
            params_for_mac['method'] = method_str

        mac_str = self._generate_create_order_mac(params_for_mac, private_key)
        _logger.info("Zalo Checkout MAC computed: %s (amount=%s, discount=%s, voucher=%s, order_name=%s)", mac_str, final_order_amount, discount_amount, voucher_code, order_name)

        return {
            'partner_id': partner.id,
            'delivery_partner_id': delivery_partner.id,
            'address_id': address_id,
            'note': body.get('note', ''),
            'payment_method': payment_method_input or 'native',
            'voucher_code': voucher_code,
            'discount_amount': discount_amount,
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
                'voucher_code': payload.get('voucher_code', ''),
                'discount_amount': payload.get('discount_amount', 0.0),
                'amount': payload['amount'],
                'desc': payload['desc'],
                'item_sdk': payload['item_sdk_json'],
                'extradata_str': payload['extradata_str'],
                'method_str': payload['method_str'],
                'mac': payload['mac'],
            })

            res_payload = {
                'prepareToken': token,
                'mac': payload['mac'],
                'amount': payload['amount'],
                'desc': payload['desc'],
                'item': payload['sdk_items'],
                'extradata': payload['extradata_str'],
            }
            if payload.get('method_str'):
                res_payload['method'] = payload['method_str']

            return self._response_success(res_payload)
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
            # Một giao dịch Zalo chỉ gắn với một đơn: callback tìm đơn theo orderId.
            if self._find_zalo_order(zalo_order_id):
                return self._response_error("INVALID_STATE", "Mã giao dịch Zalo đã được dùng cho đơn khác", 409)

            # Rebuild order lines từ items đã được chuẩn bị (chống client bịa số tiền)
            items = json.loads(prepare.items or '[]')
            order_lines = []
            for it in items:
                product_id = int(it.get('product_id'))
                qty = it.get('quantity', 1)
                # Giá đã được server tính và lưu ở bước prepare (cùng số tiền đã ký MAC).
                price_unit = float(it.get('price_unit', 0))
                product = request.env['product.product'].sudo().browse(product_id)
                if not product.exists() or price_unit <= 0:
                    continue
                order_lines.append((0, 0, {
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'price_unit': price_unit,
                    'tax_id': [(5, 0, 0)],
                    'name': product.display_name,
                }))

            if not order_lines:
                return self._response_error("INVALID_INPUT", "Không có sản phẩm hợp lệ để tạo đơn")

            delivery_partner = self._owned_address(prepare.partner_id, prepare.address_id) or prepare.partner_id
            pricelist = self._zalo_pricelist()

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
            if pricelist:
                order_vals['pricelist_id'] = pricelist.id

            sale_order = request.env['sale.order'].sudo().create(order_vals)

            # 1. Áp dụng Voucher (nếu có)
            voucher_applied = False
            if prepare.voucher_code:
                try:
                    sale_order.loyalty_voucher_code = prepare.voucher_code
                    if hasattr(sale_order, 'action_apply_loyalty_voucher'):
                        sale_order.action_apply_loyalty_voucher()
                        voucher_applied = True
                except Exception as ve:
                    _logger.warning("Checkout SDK Voucher apply error on %s: %s", sale_order.name, ve)

                # Fallback: nếu action_apply_loyalty_voucher không tạo dòng giảm giá
                if not voucher_applied and prepare.discount_amount > 0:
                    try:
                        discount_product = sale_order._get_voucher_discount_product() if hasattr(sale_order, '_get_voucher_discount_product') else False
                        if not discount_product:
                            discount_product = request.env['product.product'].sudo().search([('default_code', '=', 'LOYALTY_VOUCHER_DISCOUNT')], limit=1)
                        if discount_product:
                            request.env['sale.order.line'].sudo().create({
                                'order_id': sale_order.id,
                                'product_id': discount_product.id,
                                'name': f"Giảm giá Voucher [{prepare.voucher_code}]",
                                'product_uom_qty': 1,
                                'price_unit': -prepare.discount_amount,
                                'tax_id': [(5, 0, 0)],
                                'is_loyalty_reward_line': True,
                            })
                            voucher_applied = True
                    except Exception as fe:
                        _logger.warning("Fallback discount line error on %s: %s", sale_order.name, fe)

            # 2. Tự động xác nhận đơn hàng (chuyển từ Báo giá 'draft' sang Đơn bán hàng 'sale')
            try:
                sale_order.action_confirm()
            except Exception as ce:
                _logger.warning("Order confirm warning on %s: %s", sale_order.name, ce)

            # 3. Ghi log Chatter vào sale.order
            partner = prepare.partner_id
            note_raw = prepare.note or ""
            customer_note = re.sub(r'^\[PTTT:\s*[^\]]+\]\s*(?:-\s*Ghi chú:\s*)?', '', note_raw).strip()
            if customer_note.startswith("- Ghi chú: "):
                customer_note = customer_note[10:].strip()

            try:
                chatter_msg = Markup(
                    "<b>Đơn hàng được tạo và xác nhận từ Zalo Mini App</b><br/>"
                    "• <b>Khách hàng:</b> %s (SĐT: %s)<br/>"
                    "• <b>Phương thức thanh toán:</b> %s<br/>"
                    "• <b>Mã đơn Zalo SDK:</b> %s<br/>"
                    "• <b>Tổng tiền:</b> %s ₫"
                ) % (
                    partner.name,
                    partner.phone or partner.mobile or "N/A",
                    (prepare.payment_method or "N/A").upper(),
                    zalo_order_id,
                    f"{sale_order.amount_total:,.0f}",
                )
                if customer_note:
                    chatter_msg += Markup("<br/>• <b>Ghi chú từ khách hàng:</b> %s") % customer_note
                if prepare.voucher_code:
                    chatter_msg += Markup("<br/>• <b>Voucher:</b> %s (Giảm %s ₫)") % (prepare.voucher_code, f"{prepare.discount_amount:,.0f}")

                sale_order.message_post(body=chatter_msg, message_type="comment", subtype_xmlid="mail.mt_note")
            except Exception as me:
                _logger.warning("Post chatter error on sale.order %s: %s", sale_order.id, me)

                sale_order.message_post(body=chatter_msg, message_type="comment", subtype_xmlid="mail.mt_note")
            except Exception as me:
                _logger.warning("Post chatter error on sale.order %s: %s", sale_order.id, me)

            # 3. Gửi thông báo vào Kênh Chat Odoo (Direct Chat 1-1 & Discuss Channel)
            self._notify_order_to_discuss_channel(sale_order, payment_method=prepare.payment_method, customer_note=customer_note)

            # 4. Gửi tin nhắn Zalo về điện thoại cho các Zalo User ID (Admin/Quản lý)
            self._send_order_zalo_notification_message(sale_order, payment_method=prepare.payment_method, customer_note=customer_note)

            # 5. Gửi ZNS xác nhận đơn nếu có cấu hình
            self._send_order_zns_notification(sale_order)

            # 6. Dọn dẹp giỏ hàng tạm (zalo.miniapp.cart.line) của khách sau khi tạo đơn thành công
            try:
                CartLine = request.env["zalo.miniapp.cart.line"].sudo()
                cart_lines = CartLine.search([
                    ("partner_id", "=", partner.id),
                    ("account_id", "=", self._auth_account_id()),
                ])
                if cart_lines:
                    cart_lines.unlink()
            except Exception as cle:
                _logger.warning("Clear cart after order confirm error: %s", cle)

            prepare.write({'consumed': True})

            return self._response_success({
                'orderId': zalo_order_id,
                'odoo_id': sale_order.id,
                'order_name': sale_order.name,
                'amount': prepare.amount,
                'status': 'confirmed',
            })
        except Exception as e:
            _logger.exception("Lỗi xác nhận đơn hàng Checkout SDK: %s", str(e))
            return self._response_error("SERVER_ERROR", f"Lỗi hệ thống: {str(e)}", 500)

    # =========================================================================
    # Webhook thanh toán từ Zalo Checkout SDK Server
    # =========================================================================
    def _valid_checkout_mac(self, raw, req_mac):
        """True nếu `req_mac` đúng HMAC-SHA256(private_key, raw).

        Chưa cấu hình private key thì luôn False: trước đây thiếu key là bỏ qua
        kiểm chữ ký, ai cũng đánh dấu được đơn đã thanh toán.
        """
        private_key = self._get_private_key()
        if not private_key or not req_mac:
            return False
        calc = hmac.new(private_key.encode('utf-8'), raw.encode('utf-8'), hashlib.sha256).hexdigest()
        return hmac.compare_digest(calc.lower(), str(req_mac).lower())

    def _valid_payment_mac(self, data, req_mac):
        """Kiểm MAC kết quả thanh toán theo công thức Zalo Checkout:
        appId&amount&description&orderId&message&resultCode&transId."""
        raw = (
            f"appId={data.get('appId', '')}&amount={data.get('amount')}"
            f"&description={data.get('description', '')}&orderId={data.get('orderId', '')}"
            f"&message={data.get('message', '')}&resultCode={data.get('resultCode')}"
            f"&transId={data.get('transId', '')}"
        )
        return self._valid_checkout_mac(raw, req_mac)

    def _app_id_matches(self, app_id):
        configured = self._get_app_id()
        return not configured or str(app_id) == configured

    @staticmethod
    def _find_zalo_order(order_id):
        """Đơn theo orderId Zalo. Không lùi về tìm theo sale.order.name: orderId
        Zalo không bao giờ trùng tên đơn S0xxxx, nhánh đó chỉ giúp kẻ giả mạo
        nhắm vào đơn bất kỳ bằng tên dễ đoán."""
        if not order_id:
            return request.env['sale.order'].sudo().browse()
        return request.env['sale.order'].sudo().search([('x_zalo_order_id', '=', order_id)], limit=1)

    @staticmethod
    def _expected_payment_amount(sale_order):
        """Số tiền Zalo phải thu cho đơn: đúng số đã ký MAC ở bước prepare;
        không còn bản prepare (dữ liệu cũ) thì lấy tổng đơn."""
        prepare = request.env['zalo.miniapp.checkout.prepare'].sudo().search(
            [('order_name', '=', sale_order.name)], limit=1
        )
        return int(round(prepare.amount if prepare else sale_order.amount_total))

    def _apply_payment_result(self, sale_order, success, trans_id, method):
        if success:
            try:
                if sale_order.state == 'draft':
                    sale_order.action_confirm()
            except Exception:
                _logger.warning("Không thể tự động action_confirm cho %s", sale_order.name, exc_info=True)
            sale_order.write({
                'x_zalo_payment_status': 'paid',
                'x_zalo_trans_id': trans_id,
                'x_zalo_payment_method': method,
                'x_zalo_trans_time': fields.Datetime.now(),
            })
        else:
            sale_order.write({
                'x_zalo_payment_status': 'failed',
                'x_zalo_trans_id': trans_id,
                'x_zalo_payment_method': method,
            })

    def _check_payment_notification(self, data, req_mac):
        """Kiểm một thông báo kết quả thanh toán; trả (sale_order, lỗi).

        Ngoài chữ ký còn so appId và SỐ TIỀN: chữ ký đúng chỉ chứng minh Zalo
        đã thu `amount` cho `orderId`, không chứng minh đó là số tiền của đơn
        (khách có thể gắn orderId của một giao dịch rẻ vào đơn đắt ở /confirm).
        """
        if not self._valid_payment_mac(data, req_mac):
            _logger.warning("Zalo Checkout: sai chữ ký cho orderId=%s", data.get('orderId'))
            return None, 'Invalid MAC signature'
        if not self._app_id_matches(data.get('appId', '')):
            return None, 'Invalid appId'
        sale_order = self._find_zalo_order(str(data.get('orderId', '')))
        if not sale_order:
            return None, 'Order not found'
        if data.get('resultCode') == 1:
            expected = self._expected_payment_amount(sale_order)
            if self._parse_int(data.get('amount'), -1) != expected:
                _logger.warning(
                    "Zalo Checkout: số tiền lệch cho %s (Zalo %s, đơn %s)",
                    sale_order.name, data.get('amount'), expected,
                )
                return None, 'Amount mismatch'
        return sale_order, None

    @http.route('/api/zalo/checkout/callback', type='json', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def zalo_checkout_callback(self, **post):
        """
        Webhook nhận kết quả thanh toán từ Zalo Checkout SDK Server.
        Payload: {"data": {"appId", "orderId", "transId", "method", "transTime",
                           "amount", "description", "resultCode", "message"},
                  "mac": "...", "overallMac": "..."}
        """
        if request.httprequest.method == 'OPTIONS':
            return self._response_options()
        try:
            body = self._request_json()
            data = body.get('data') or {}
            if not data:
                return {'returnCode': -1, 'returnMessage': 'Missing data payload'}

            sale_order, error = self._check_payment_notification(data, body.get('mac', ''))
            if error:
                return {'returnCode': -1, 'returnMessage': error}

            if sale_order.x_zalo_payment_status == 'paid':
                return {'returnCode': 2, 'returnMessage': 'Order already processed'}

            success = data.get('resultCode') == 1
            self._apply_payment_result(
                sale_order, success, str(data.get('transId', '')), str(data.get('method', '')),
            )
            if success:
                _logger.info("Zalo Checkout Callback THÀNH CÔNG cho đơn %s", sale_order.name)
                return {'returnCode': 1, 'returnMessage': 'Success'}
            _logger.warning("Zalo Checkout Callback THẤT BẠI cho đơn %s: %s", sale_order.name, data.get('message'))
            return {'returnCode': 1, 'returnMessage': 'Failure recorded'}
        except Exception:
            _logger.exception("Lỗi khi xử lý Callback Zalo Checkout SDK")
            return {'returnCode': -1, 'returnMessage': 'Internal Server Error'}

    @http.route('/api/zalo/checkout/notify', type='json', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def zalo_checkout_notify(self, **post):
        """
        Webhook nhận thông báo khi người dùng chọn phương thức COD hoặc Bank Transfer.
        Payload: {"data": {"appId", "orderId", "method"}, "mac": "..."}
        """
        if request.httprequest.method == 'OPTIONS':
            return self._response_options()
        try:
            body = self._request_json()
            data = body.get('data') or {}
            app_id = str(data.get('appId', ''))
            order_id = str(data.get('orderId', ''))
            method = str(data.get('method', ''))

            raw = f"appId={app_id}&orderId={order_id}&method={method}"
            if not self._valid_checkout_mac(raw, body.get('mac', '')) or not self._app_id_matches(app_id):
                return {'returnCode': -1, 'returnMessage': 'Invalid MAC signature'}

            sale_order = self._find_zalo_order(order_id)
            if sale_order:
                sale_order.write({'x_zalo_payment_method': method})
                _logger.info("Zalo Checkout Notify: Đơn %s ghi nhận phương thức %s", sale_order.name, method)

            return {'returnCode': 1, 'returnMessage': 'Success'}
        except Exception:
            _logger.exception("Lỗi khi xử lý Notify Zalo Checkout")
            return {'returnCode': -1, 'returnMessage': 'Internal Server Error'}

    @http.route('/api/zalo/checkout/vnpay_ipn', type='json', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def zalo_checkout_vnpay_ipn(self, **post):
        """
        IPN cho giao dịch VNPay qua Zalo Checkout SDK.

        Trước đây không kiểm gì: gửi {"orderId": <tên đơn>, "vnp_ResponseCode": "00"}
        là đơn bị đánh dấu đã thanh toán. Giờ bắt buộc cùng chữ ký / appId /
        số tiền như /callback (thông báo thật từ Zalo Checkout đều ký theo
        công thức đó); thông báo không có chữ ký Zalo bị từ chối.
        """
        if request.httprequest.method == 'OPTIONS':
            return self._response_options()
        try:
            body = self._request_json()
            data = body.get('data') or {}
            if not data.get('orderId'):
                return {'RspCode': '99', 'Message': 'Invalid OrderId'}

            sale_order, error = self._check_payment_notification(data, body.get('mac', ''))
            if error == 'Order not found':
                return {'RspCode': '01', 'Message': error}
            if error == 'Amount mismatch':
                return {'RspCode': '04', 'Message': 'Invalid Amount'}
            if error:
                return {'RspCode': '97', 'Message': 'Invalid Signature'}

            if sale_order.x_zalo_payment_status == 'paid':
                return {'RspCode': '02', 'Message': 'Order already confirmed'}

            success = data.get('resultCode') == 1
            self._apply_payment_result(sale_order, success, str(data.get('transId', '')), 'VNPAY')
            if success:
                return {'RspCode': '00', 'Message': 'Confirm Success'}
            return {'RspCode': '00', 'Message': 'Transaction Failed Recorded'}
        except Exception:
            _logger.exception("Lỗi khi xử lý VNPay IPN Webhook")
            return {'RspCode': '99', 'Message': 'Unknown error'}
