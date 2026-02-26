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
        required=True,
        help="Chọn shop Shopee để lấy access_token và shop_identifier",
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

    def _parse_order_sn_list(self):
        """Parse order SN list từ input text (hỗ trợ nhiều dòng hoặc dấu phẩy)."""
        self.ensure_one()
        raw = self.order_sn_list or ''
        # Hỗ trợ cả xuống dòng lẫn dấu phẩy
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

    def action_fetch_order(self):
        """Gọi Shopee API get_order_detail và hiển thị kết quả. Không ghi DB."""
        self.ensure_one()

        # --- 1. Đọc credentials từ shop ---
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

        # Validate
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

        # --- 2. Parse order SN list ---
        sns = self._parse_order_sn_list()
        order_sn_str = ','.join(sns)

        # --- 3. Tạo timestamp & sign ---
        api_path = '/api/v2/order/get_order_detail'
        ts = int(time.time())
        sign = self._generate_sign(partner_id, api_path, ts, access_token, shop_identifier, partner_key)

        # --- 4. Gọi Shopee API ---
        shopee_url = f"https://partner.shopeemobile.com{api_path}"
        params = {
            'partner_id': partner_id,
            'timestamp': ts,
            'access_token': access_token,
            'shop_id': shop_identifier,
            'sign': sign,
            'order_sn_list': order_sn_str,
        }

        # Optional fields
        opt_fields = self.response_optional_fields
        if opt_fields:
            # Loại bỏ khoảng trắng thừa
            params['response_optional_fields'] = ','.join(
                f.strip() for f in opt_fields.split(',') if f.strip()
            )

        _logger.info("Shopee API get_order_detail – params: %s", params)

        try:
            resp = req_lib.get(shopee_url, params=params, timeout=30)
        except Exception as e:
            raise UserError(_("Lỗi kết nối tới Shopee API:\n%s") % str(e))

        # --- 5. Xử lý response ---
        try:
            body = resp.json()
        except Exception:
            body = resp.text

        result = {
            'shopee_http_status': resp.status_code,
            'shopee_response': body,
            'request_params_sent': {
                k: v for k, v in params.items()
                if k not in ('sign',)  # Ẩn sign cho gọn
            },
        }

        _logger.info("Shopee API response – status=%s", resp.status_code)

        # Hiển thị kết quả
        self.result_display = json.dumps(result, indent=2, ensure_ascii=False)

        # Trả về wizard để user xem kết quả (giữ wizard mở)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
