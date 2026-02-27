# -*- coding: utf-8 -*-
import json
import time
import hashlib
import hmac
import logging

import requests as req_lib

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Các trường optional mặc định lấy đầy đủ từ Shopee
_DEFAULT_OPTIONAL_FIELDS = (
    "buyer_user_id,buyer_username,estimated_shipping_fee,recipient_address,"
    "actual_shipping_fee,goods_to_declare,note,note_update_time,item_list,"
    "pay_time,dropshipper,dropshipper_phone,split_up,buyer_cancel_reason,"
    "cancel_by,cancel_reason,actual_shipping_fee_confirmed,buyer_cpf_id,"
    "fulfillment_flag,pickup_done_time,package_list,shipping_carrier,"
    "payment_method,total_amount,buyer_username,invoice_data,"
    "order_chargeable_weight_gram,return_request_due_date,edt,payment_info"
)


class ShopeeOrderFetchWizard(models.TransientModel):
    _name = 'shopee.order.fetch.wizard'
    _description = 'Lấy thông tin đơn hàng Shopee qua API'

    shop_id = fields.Many2one(
        'shopee.shop',
        string='Shop Shopee',
        required=False,
        help="Chọn shop Shopee để lấy access_token và shop_identifier. Bỏ trống nếu test mock data.",
    )
    order_sn_list = fields.Text(
        string='Mã đơn hàng Shopee',
        required=True,
        help="Nhập mã đơn hàng Shopee, mỗi dòng 1 mã hoặc cách nhau bởi dấu phẩy. Tối đa 50 đơn.",
    )
    response_optional_fields = fields.Char(
        string='Response Optional Fields',
        default=_DEFAULT_OPTIONAL_FIELDS,
        help="Các trường tùy chọn muốn lấy từ Shopee API, cách nhau bởi dấu phẩy.",
    )
    result_display = fields.Text(
        string='Kết quả API',
        readonly=True,
    )
    mock_json = fields.Text(
        string='Mock JSON - Order Detail',
        help="Dán JSON response từ Shopee get_order_detail API vào đây để test tạo đơn.",
    )
    mock_escrow_json = fields.Text(
        string='Mock JSON - Escrow Detail',
        help="Dán JSON response từ Shopee get_escrow_detail API vào đây để áp dụng voucher.",
    )
    sale_order_ids = fields.Many2many(
        'sale.order',
        string='Mã đơn Odoo (thủ công)',
        help="Chọn các đơn Odoo (ví dụ S00001) tương ứng với các mã Shopee ở trên (theo thứ tự từ trên xuống). Dùng khi mã Odoo chưa được lưu mã Shopee (shopee_order_ref) và không tự tìm được."
    )

    # ──────────────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────────────

    def _parse_order_sn_list(self):
        """Parse order SN list từ input text (hỗ trợ nhiều dòng hoặc dấu phẩy)."""
        self.ensure_one()
        raw = self.order_sn_list or ''
        sns = []
        for line in raw.replace('\r', '').split('\n'):
            for sn in line.split(','):
                sn = sn.strip()
                if sn:
                    sns.append(sn)
        if not sns:
            raise UserError(_("Vui lòng nhập ít nhất 1 mã đơn hàng Shopee."))
        if len(sns) > 50:
            raise UserError(_("Shopee API chỉ hỗ trợ tối đa 50 đơn hàng mỗi lần gọi."))
        return sns

    def _generate_sign(self, partner_id, api_path, timestamp, access_token, shop_id, partner_key):
        """Tạo HMAC-SHA256 sign theo spec Shopee Open API v2."""
        base_string = f"{partner_id}{api_path}{timestamp}{access_token}{shop_id}"
        sign = hmac.new(
            partner_key.encode('utf-8'),
            base_string.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        return sign

    def _get_shopee_credentials(self):
        """Đọc credentials từ shop đã chọn. Trả về dict."""
        self.ensure_one()
        shop = self.shop_id
        if not shop:
            raise UserError(_("Vui lòng chọn Shop Shopee."))

        access_token = getattr(shop, 'access_token', False)
        shop_identifier = getattr(shop, 'shop_identifier', False)

        account = getattr(shop, 'account_id', False)
        if not account:
            raise UserError(_("Shop '%s' chưa được liên kết với Shopee Account.") % shop.display_name)

        partner_id = getattr(account, 'partner_identifier', False)
        partner_key = getattr(account, 'partner_key', False)

        missing = []
        if not partner_id:
            missing.append('partner_identifier (Shopee Account)')
        if not partner_key:
            missing.append('partner_key (Shopee Account)')
        if not access_token:
            missing.append('access_token (Shopee Shop)')
        if not shop_identifier:
            missing.append('shop_identifier (Shopee Shop)')
        if missing:
            raise UserError(
                _("Thiếu thông tin cấu hình:\n%s") % '\n'.join(f"- {m}" for m in missing)
            )

        return {
            'partner_id': partner_id,
            'partner_key': partner_key,
            'access_token': access_token,
            'shop_identifier': shop_identifier,
        }

    def _call_shopee_api(self, creds, order_sn_str):
        """Gọi Shopee get_order_detail API, trả về parsed JSON body."""
        api_path = '/api/v2/order/get_order_detail'
        ts = int(time.time())
        sign = self._generate_sign(
            creds['partner_id'], api_path, ts,
            creds['access_token'], creds['shop_identifier'],
            creds['partner_key'],
        )

        params = {
            'partner_id': creds['partner_id'],
            'timestamp': ts,
            'access_token': creds['access_token'],
            'shop_id': creds['shop_identifier'],
            'sign': sign,
            'order_sn_list': order_sn_str,
        }

        opt_fields = self.response_optional_fields
        if opt_fields:
            params['response_optional_fields'] = ','.join(
                f.strip() for f in opt_fields.split(',') if f.strip()
            )

        _logger.info("Shopee API get_order_detail – params: %s", params)

        try:
            resp = req_lib.get(
                f"https://partner.shopeemobile.com{api_path}",
                params=params, timeout=30,
            )
        except Exception as e:
            raise UserError(_("Lỗi kết nối tới Shopee API:\n%s") % str(e))

        try:
            body = resp.json()
        except Exception:
            raise UserError(_("Shopee trả về response không hợp lệ:\n%s") % resp.text)

        return resp.status_code, body, params

    def _call_escrow_api(self, creds, order_sn):
        """Gọi Shopee get_escrow_detail API để lấy thông tin thanh toán chi tiết."""
        api_path = '/api/v2/payment/get_escrow_detail'
        ts = int(time.time())
        sign = self._generate_sign(
            creds['partner_id'], api_path, ts,
            creds['access_token'], creds['shop_identifier'],
            creds['partner_key'],
        )

        params = {
            'partner_id': creds['partner_id'],
            'timestamp': ts,
            'access_token': creds['access_token'],
            'shop_id': creds['shop_identifier'],
            'sign': sign,
            'order_sn': order_sn,
        }

        _logger.info("Shopee API get_escrow_detail – order_sn=%s", order_sn)

        try:
            resp = req_lib.get(
                f"https://partner.shopeemobile.com{api_path}",
                params=params, timeout=30,
            )
            body = resp.json()
        except Exception as e:
            _logger.warning("Shopee: Lỗi gọi escrow API cho %s: %s", order_sn, str(e))
            return None

        if body.get('error'):
            _logger.warning(
                "Shopee escrow API error cho %s: %s - %s",
                order_sn, body.get('error'), body.get('message'),
            )
            return None

        return body.get('response', {})

    # ──────────────────────────────────────────────────
    #  Action: Chỉ lấy thông tin (read-only)
    # ──────────────────────────────────────────────────

    def action_fetch_order(self):
        """Gọi Shopee API get_order_detail và hiển thị kết quả. Không ghi DB."""
        self.ensure_one()

        creds = self._get_shopee_credentials()
        sns = self._parse_order_sn_list()
        status_code, body, params = self._call_shopee_api(creds, ','.join(sns))

        result = {
            'shopee_http_status': status_code,
            'shopee_response': body,
            'request_params_sent': {
                k: v for k, v in params.items() if k != 'sign'
            },
        }
        self.result_display = json.dumps(result, indent=2, ensure_ascii=False)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ──────────────────────────────────────────────────
    #  Action: Lấy thông tin + Tạo đơn hàng
    # ──────────────────────────────────────────────────

    def action_fetch_and_create_order(self):
        """Gọi Shopee API, sau đó tạo Sale Order từ response."""
        self.ensure_one()

        creds = self._get_shopee_credentials()
        sns = self._parse_order_sn_list()
        status_code, body, params = self._call_shopee_api(creds, ','.join(sns))

        # Validate response
        if status_code != 200:
            raise UserError(
                _("Shopee API trả về lỗi (HTTP %s):\n%s")
                % (status_code, json.dumps(body, indent=2, ensure_ascii=False))
            )

        error_msg = body.get('error', '')
        if error_msg:
            raise UserError(
                _("Shopee API error: %s\n%s") % (error_msg, body.get('message', ''))
            )

        order_list = body.get('response', {}).get('order_list', [])
        if not order_list:
            raise UserError(_("Shopee API không trả về đơn hàng nào."))

        created_orders = []
        skipped_orders = []

        for order_data in order_list:
            order_sn = order_data.get('order_sn', '')

            # Kiểm tra đơn đã tồn tại chưa
            existing = self.env['sale.order'].sudo().search([
                ('shopee_order_ref', '=', order_sn)
            ], limit=1)
            if existing:
                skipped_orders.append(f"{order_sn} (đã tồn tại: {existing.name})")
                continue

            try:
                with self.env.cr.savepoint():
                    # Gọi escrow API để lấy voucher (best-effort)
                    escrow_data = None
                    try:
                        escrow_data = self._call_escrow_api(creds, order_sn)
                    except Exception as esc_err:
                        _logger.warning("Shopee: Không lấy được escrow cho %s: %s", order_sn, str(esc_err))

                    so = self._create_order_from_data(order_data, escrow_data=escrow_data)
                    created_orders.append(f"{order_sn} → {so.name}")
            except Exception as e:
                _logger.error("Shopee: Lỗi tạo đơn %s: %s", order_sn, str(e), exc_info=True)
                skipped_orders.append(f"{order_sn} (LỖI: {str(e)})")

        # Hiển thị kết quả
        lines = []
        if created_orders:
            lines.append("✅ ĐÃ TẠO:")
            lines.extend(f"  • {o}" for o in created_orders)
        if skipped_orders:
            lines.append("\n⏭️ BỎ QUA:")
            lines.extend(f"  • {o}" for o in skipped_orders)

        self.sudo().result_display = '\n'.join(lines)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ──────────────────────────────────────────────────
    #  Action: Cập nhật giá từ Escrow
    # ──────────────────────────────────────────────────

    def action_update_price_from_escrow(self):
        """Gọi Shopee API get_escrow_detail hoặc đọc từ mock json để cập nhật lại giá cho đơn hàng đã tồn tại."""
        self.ensure_one()

        sns = self._parse_order_sn_list()

        # Parse Escrow JSON (tùy chọn) trước
        mock_escrow_data = None
        if self.mock_escrow_json:
            try:
                escrow_raw = json.loads(self.mock_escrow_json)
                mock_escrow_data = escrow_raw.get('response', escrow_raw)
            except json.JSONDecodeError as e:
                raise UserError(_("Mock Escrow JSON không hợp lệ:\n%s") % str(e))

        creds = None
        if not mock_escrow_data:
             creds = self._get_shopee_credentials()

        updated_orders = []
        skipped_orders = []
        manual_orders = list(self.sale_order_ids)

        for i, order_sn in enumerate(sns):
            so = self.env['sale.order'].sudo().search([
                ('shopee_order_ref', '=', order_sn)
            ], limit=1)

            if not so:
                if i < len(manual_orders):
                    so = manual_orders[i]
                    so.sudo().write({'shopee_order_ref': order_sn})
                    _logger.info("Shopee: Đã gán mã Shopee %s cho đơn Odoo %s", order_sn, so.name)
                else:
                    skipped_orders.append(f"{order_sn} (Không tìm thấy đơn hàng trong hệ thống)")
                    continue

            # Nếu không tìm được Order Detail, thử dùng dữ liệu từ Escrow (nếu có items)
            try:
                escrow_data = mock_escrow_data
                if not escrow_data and creds:
                    escrow_data = self._call_escrow_api(creds, order_sn)
            except Exception as e:
                _logger.warning("Shopee: Lỗi gọi escrow API: %s", str(e))
                escrow_data = None

            if escrow_data and escrow_data.get('order_income', {}).get('items'):
                # Escrow có items -> update giá theo escrow items
                self._update_order_lines_from_data(so, escrow_data.get('order_income', {}))

            # --- Apply Escrow Voucher ---
            try:
                if escrow_data:
                    self._apply_escrow_voucher(so, escrow_data)
                    updated_orders.append(f"{order_sn} → Đã cập nhật giá (Escrow)")
                else:
                    skipped_orders.append(f"{order_sn} (Không có dữ liệu Escrow từ Shopee)")
            except Exception as e:
                _logger.error("Shopee: Lỗi cập nhật giá Escrow cho %s: %s", order_sn, str(e), exc_info=True)
                skipped_orders.append(f"{order_sn} (LỖI: {str(e)})")

        lines = []
        if updated_orders:
            lines.append("✅ ĐÃ CẬP NHẬT GIÁ:")
            lines.extend(f"  • {o}" for o in updated_orders)
        if skipped_orders:
            lines.append("\n⏭️ BỎ QUA:")
            lines.extend(f"  • {o}" for o in skipped_orders)

        self.sudo().result_display = '\n'.join(lines)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ──────────────────────────────────────────────────
    #  Order creation helpers
    # ──────────────────────────────────────────────────

    def _create_order_from_data(self, order_data, escrow_data=None):
        """Tạo sale.order từ 1 order trong Shopee response."""
        shop = self.shop_id

        # 1. Tạo / tìm partner + địa chỉ giao hàng
        partner, delivery_address = self._find_or_create_partner(order_data)

        # 2. Tìm kho TSN mặc định
        warehouse = self.env['stock.warehouse'].sudo().search(
            [('code', '=', 'TSN')], limit=1
        )

        # 3. Tạo sale.order
        so_vals = {
            'partner_id': partner.id,
            'shopee_order_ref': order_data.get('order_sn', ''),
            'shopee_order_status': order_data.get('order_status', ''),
        }
        if delivery_address:
            so_vals['partner_shipping_id'] = delivery_address.id
        if shop:
            so_vals['shopee_shop_id'] = shop.id
        if warehouse:
            so_vals['warehouse_id'] = warehouse.id
        so = self.env['sale.order'].sudo().create(so_vals)

        # 4. Tạo sale.order.line từ item_list
        item_list = order_data.get('item_list', [])
        for item_data in item_list:
            self._create_order_line(so, item_data, shop)

        # 5. Áp dụng shopee_voucher từ escrow (phân bổ vào chiết khấu các dòng)
        if escrow_data:
            self._apply_escrow_voucher(so, escrow_data)

        # 6. Xác nhận báo giá → tạo phiếu giao hàng (picking)
        try:
            so.sudo().action_confirm()
            _logger.info(
                "Shopee: Đã xác nhận đơn hàng %s → picking đã tạo",
                so.name,
            )
        except Exception as e:
            _logger.warning(
                "Shopee: Không thể xác nhận đơn %s: %s",
                so.name, str(e),
            )

        _logger.info(
            "Shopee: Đã tạo đơn hàng %s từ order_sn=%s",
            so.name, order_data.get('order_sn'),
        )
        return so

    def _find_or_create_partner(self, order_data):
        """Tìm hoặc tạo res.partner từ buyer_username.
        Tạo thêm địa chỉ giao hàng (type=delivery) từ recipient_address."""
        Partner = self.env['res.partner'].sudo()

        buyer_username = order_data.get('buyer_username', '') or 'Khách Shopee'
        addr = order_data.get('recipient_address', {}) or {}

        # Tìm partner theo buyer_username
        partner = Partner.search([('name', '=', buyer_username)], limit=1)

        # Tạo mới nếu chưa có
        if not partner:
            partner = Partner.create({
                'name': buyer_username,
                'customer_rank': 1,
            })
            _logger.info("Shopee: Đã tạo liên hệ '%s' (ID: %s)", partner.name, partner.id)

        # Tạo địa chỉ giao hàng (child contact) nếu có recipient_address
        delivery_address = self._find_or_create_delivery_address(partner, addr)

        return partner, delivery_address

    def _find_or_create_delivery_address(self, parent_partner, addr):
        """Tạo địa chỉ giao hàng (type=delivery) dưới partner chính."""
        if not addr:
            return False

        Partner = self.env['res.partner'].sudo()

        recipient_name = addr.get('name', '')
        phone = addr.get('phone', '')
        full_address = addr.get('full_address', '')

        # Nếu tất cả đều bị mask (****) thì bỏ qua
        if all(v in ('', '****') for v in [recipient_name, phone, full_address]):
            return False

        # Tìm delivery address đã tồn tại dưới partner
        domain = [
            ('parent_id', '=', parent_partner.id),
            ('type', '=', 'delivery'),
        ]
        if phone and phone != '****':
            domain.append(('phone', '=', phone))
        existing = Partner.search(domain, limit=1)
        if existing:
            return existing

        # Tạo mới
        delivery_vals = {
            'parent_id': parent_partner.id,
            'type': 'delivery',
            'name': recipient_name if recipient_name and recipient_name != '****' else parent_partner.name,
        }
        if phone and phone != '****':
            delivery_vals['phone'] = phone
        if full_address and full_address != '****':
            delivery_vals['street'] = full_address
        if addr.get('city') and addr['city'] != '****':
            delivery_vals['city'] = addr['city']
        if addr.get('district') and addr['district'] != '****':
            delivery_vals['street2'] = addr['district']
        if addr.get('state') and addr['state'] != '****':
            delivery_vals['city'] = (delivery_vals.get('city', '') + ', ' + addr['state']).strip(', ')

        delivery = Partner.create(delivery_vals)
        _logger.info(
            "Shopee: Đã tạo địa chỉ giao hàng cho '%s' (ID: %s)",
            parent_partner.name, delivery.id,
        )
        return delivery

    def _find_or_create_shopee_item(self, item_data, shop):
        """Tìm hoặc tạo shopee.item từ item_data. Trả về product.product."""
        ShopeeItem = self.env['shopee.item'].sudo()

        item_id = item_data.get('item_id', 0)
        model_id = item_data.get('model_id', 0)
        item_name = item_data.get('item_name', '')
        model_sku = item_data.get('model_sku', '')

        # 1. Tìm shopee.item theo shopee_item_identifier + shopee_model_identifier
        domain = [('shopee_item_identifier', '=', item_id)]
        if model_id:
            domain.append(('shopee_model_identifier', '=', model_id))
        existing_item = ShopeeItem.search(domain, limit=1)

        if existing_item and existing_item.product_id:
            return existing_item.product_id

        # 2. Tìm product.product theo model_sku (default_code)
        product = False
        if model_sku:
            product = self.env['product.product'].sudo().search([
                ('default_code', '=', model_sku)
            ], limit=1)

        # 3. Nếu chưa có product, tìm theo tên
        if not product and item_name:
            product = self.env['product.product'].sudo().search([
                ('name', '=', item_name)
            ], limit=1)

        # 4. Nếu vẫn chưa có, tạo product mới
        if not product:
            product = self.env['product.product'].sudo().create({
                'name': item_name or f"Shopee Item {item_id}",
                'default_code': model_sku or '',
                'type': 'consu',
                'sale_ok': True,
            })
            _logger.info("Shopee: Đã tạo sản phẩm '%s' (SKU: %s)", product.name, model_sku)

        # 5. Tạo shopee.item nếu chưa có VÀ có shop
        if not existing_item and shop:
            shopee_item_vals = {
                'shopee_item_identifier': item_id,
                'product_id': product.id,
                'shop_id': shop.id,
            }
            if model_id:
                shopee_item_vals['shopee_model_identifier'] = model_id
            ShopeeItem.create(shopee_item_vals)
            _logger.info(
                "Shopee: Đã tạo shopee.item (item_id=%s, model_id=%s) → product=%s",
                item_id, model_id, product.name,
            )

        return product

    def _create_order_line(self, so, item_data, shop):
        """Tạo sale.order.line từ 1 item trong Shopee response."""
        product = self._find_or_create_shopee_item(item_data, shop)

        qty = item_data.get('model_quantity_purchased', 1)
        original_price = item_data.get('model_original_price', 0)
        discounted_price = item_data.get('model_discounted_price', 0)

        # Tính chiết khấu %: không làm tròn để giữ chính xác
        discount = 0.0
        if original_price and discounted_price and original_price > 0:
            discount = (original_price - discounted_price) / original_price * 100

        line_vals = {
            'order_id': so.id,
            'product_id': product.id,
            'name': product.name,
            'product_uom_qty': qty,
            'price_unit': original_price,
            'discount': discount,
        }

        # Shopee giá đã bao gồm thuế → dùng thuế "đã bao gồm trong giá" (price_include=True)
        tax_included = self._get_tax_included(so.company_id)
        if tax_included:
            line_vals['tax_id'] = [(6, 0, tax_included.ids)]

        return self.env['sale.order.line'].sudo().create(line_vals)

    def _get_tax_included(self, company):
        """Tìm thuế bán hàng có price_include=True (thuế đã bao gồm trong giá)."""
        Tax = self.env['account.tax'].sudo()

        # Tìm thuế sale có price_include=True
        tax = Tax.search([
            ('type_tax_use', '=', 'sale'),
            ('price_include', '=', True),
            ('company_id', '=', company.id),
        ], limit=1)

        if tax:
            return tax

        # Nếu không có, lấy thuế mặc định công ty và tìm bản price_include
        default_tax = company.account_sale_tax_id
        if default_tax:
            tax = Tax.search([
                ('type_tax_use', '=', 'sale'),
                ('price_include', '=', True),
                ('amount', '=', default_tax.amount),
                ('company_id', '=', company.id),
            ], limit=1)
            if tax:
                return tax

        return False

    def _update_order_lines_from_data(self, so, order_data):
        """Cập nhật giá và chiết khấu cho các sale.order.line hiện tại từ data (Order Detail hoặc Escrow)."""
        # Hỗ trợ cả trường hợp data là từ get_order_detail (có 'item_list')
        # Hoặc data là từ get_escrow_detail.order_income (có 'items')
        
        item_list = order_data.get('item_list', [])
        if not item_list:
            item_list = order_data.get('items', [])
            
        for item_data in item_list:
            model_sku = item_data.get('model_sku', '') or item_data.get('item_sku', '')
            if not model_sku:
                continue
            
            # Tìm line tương ứng trong so theo mã nội bộ (default_code)
            line = so.order_line.filtered(lambda l: l.product_id.default_code == model_sku)
            if not line:
                continue
                
            qty = item_data.get('model_quantity_purchased', item_data.get('quantity_purchased', 1))
            original_price = item_data.get('model_original_price', item_data.get('original_price', 0))
            discounted_price = item_data.get('model_discounted_price', item_data.get('discounted_price', 0))

            discount = 0.0
            if original_price and discounted_price and original_price > 0:
                discount = (original_price - discounted_price) / original_price * 100

            line_vals = {
                'price_unit': original_price,
                'discount': discount,
            }
            
            tax_included = self._get_tax_included(so.company_id)
            if tax_included:
                line_vals['tax_id'] = [(6, 0, tax_included.ids)]
                
            line.sudo().write(line_vals)
            _logger.info("Shopee: Đã update giá dòng %s: price=%s, discount=%s", model_sku, original_price, discount)

    def _apply_escrow_voucher(self, so, escrow_data):
        """Áp dụng voucher của Shop từ escrow response.
        Chỉ giảm giá phần voucher do Shop chịu (voucher_from_seller), 
        phần Shopee tài trợ vẫn được tính vào doanh thu."""
        order_income = escrow_data.get('order_income', {})
        seller_voucher = order_income.get('voucher_from_seller', 0)

        # Fallback lấy từ buyer_payment_info nếu không có order_income
        if not seller_voucher:
            buyer_payment = escrow_data.get('buyer_payment_info', {})
            seller_voucher = abs(buyer_payment.get('seller_voucher', 0))

        total_voucher = abs(seller_voucher)

        if total_voucher <= 0:
            return

        # Lấy tất cả order lines có giá
        lines = so.order_line.filtered(lambda l: not l.display_type and l.price_unit > 0)
        if not lines:
            return

        # Tính tổng giá trị sau chiết khấu hiện tại (trước voucher)
        total_before_voucher = sum(
            l.price_unit * l.product_uom_qty * (1 - l.discount / 100)
            for l in lines
        )

        if total_before_voucher <= 0:
            return

        # Phân bổ voucher và tăng discount %
        voucher_distributed = 0
        lines_list = list(lines)

        for i, line in enumerate(lines_list):
            line_total = line.price_unit * line.product_uom_qty
            if line_total <= 0:
                continue

            line_subtotal_before = line_total * (1 - line.discount / 100)

            if i < len(lines_list) - 1:
                line_voucher_share = int(
                    (line_subtotal_before / total_before_voucher) * total_voucher
                )
            else:
                line_voucher_share = total_voucher - voucher_distributed

            voucher_distributed += line_voucher_share

            # Tính discount mới: không làm tròn
            new_subtotal = line_subtotal_before - line_voucher_share
            new_discount = (1 - new_subtotal / line_total) * 100
            line.sudo().write({'discount': new_discount})

        _logger.info(
            "Shopee: Đã áp dụng voucher -%s vào discount các dòng của đơn %s",
            total_voucher, so.name,
        )

    # ──────────────────────────────────────────────────
    #  Action: Test tạo đơn với mock JSON (staging)
    # ──────────────────────────────────────────────────

    def action_test_create_order(self):
        """Tạo đơn hàng từ mock JSON response (dùng cho staging test).
        Không gọi Shopee API — lấy dữ liệu từ trường mock_json."""
        self.ensure_one()

        if not self.mock_json:
            raise UserError(_(
                "Vui lòng dán JSON response từ Shopee get_order_detail API vào trường 'Mock JSON - Order Detail'.\n"
                "Bạn có thể lấy response bằng cách gọi API trên production hoặc dùng Postman."
            ))

        # Parse Order Detail JSON
        try:
            data = json.loads(self.mock_json)
        except json.JSONDecodeError as e:
            raise UserError(_("Order Detail JSON không hợp lệ:\n%s") % str(e))

        # Hỗ trợ cả format đầy đủ (có shopee_response wrapper) và format trực tiếp
        if 'shopee_response' in data:
            body = data['shopee_response']
        elif 'response' in data:
            body = data
        else:
            raise UserError(_(
                "JSON không đúng format. Cần có key 'shopee_response' hoặc 'response'."
            ))

        error_msg = body.get('error', '')
        if error_msg:
            raise UserError(
                _("Response chứa lỗi: %s\n%s") % (error_msg, body.get('message', ''))
            )

        order_list = body.get('response', {}).get('order_list', [])
        if not order_list:
            raise UserError(_("Không tìm thấy order_list trong JSON."))

        # Parse Escrow JSON (tùy chọn)
        escrow_data = None
        if self.mock_escrow_json:
            try:
                escrow_raw = json.loads(self.mock_escrow_json)
                escrow_data = escrow_raw.get('response', escrow_raw)
            except json.JSONDecodeError as e:
                _logger.warning("Escrow JSON parse error: %s", str(e))

        created_orders = []
        skipped_orders = []

        for order_data in order_list:
            order_sn = order_data.get('order_sn', '')

            # Kiểm tra trùng
            existing = self.env['sale.order'].sudo().search([
                ('shopee_order_ref', '=', order_sn)
            ], limit=1)
            if existing:
                skipped_orders.append(f"{order_sn} (đã tồn tại: {existing.name})")
                continue

            try:
                with self.env.cr.savepoint():
                    so = self._create_order_from_data(order_data, escrow_data=escrow_data)
                    created_orders.append(f"{order_sn} → {so.name}")
            except Exception as e:
                _logger.error("Shopee Mock: Lỗi tạo đơn %s: %s", order_sn, str(e), exc_info=True)
                skipped_orders.append(f"{order_sn} (LỖI: {str(e)})")

        # Hiển thị kết quả
        lines = ["📋 KẾT QUẢ TEST (Mock Data):"]
        if created_orders:
            lines.append("\n✅ ĐÃ TẠO:")
            lines.extend(f"  • {o}" for o in created_orders)
        if skipped_orders:
            lines.append("\n⏭️ BỎ QUA:")
            lines.extend(f"  • {o}" for o in skipped_orders)
        if not created_orders and not skipped_orders:
            lines.append("\n⚠️ Không có đơn hàng nào để xử lý.")

        self.sudo().result_display = '\n'.join(lines)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

