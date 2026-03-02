# -*- coding: utf-8 -*-
"""
services/shopee_api.py

Toàn bộ logic giao tiếp với Shopee Open API v2.
Không phụ thuộc vào bất kỳ model Odoo nào — chỉ nhận env+record làm tham số.
"""
import hashlib
import hmac
import logging
import time

import requests as req_lib

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SHOPEE_BASE_URL = 'https://partner.shopeemobile.com'

# Các trường optional mặc định lấy đầy đủ từ Shopee
DEFAULT_OPTIONAL_FIELDS = (
    "buyer_user_id,buyer_username,estimated_shipping_fee,recipient_address,"
    "actual_shipping_fee,goods_to_declare,note,note_update_time,item_list,"
    "pay_time,dropshipper,dropshipper_phone,split_up,buyer_cancel_reason,"
    "cancel_by,cancel_reason,actual_shipping_fee_confirmed,buyer_cpf_id,"
    "fulfillment_flag,pickup_done_time,package_list,shipping_carrier,"
    "payment_method,total_amount,buyer_username,invoice_data,"
    "order_chargeable_weight_gram,return_request_due_date,edt,payment_info"
)


# ──────────────────────────────────────────────────────
#  Helpers nội bộ
# ──────────────────────────────────────────────────────

def generate_sign(partner_id, api_path, timestamp, access_token, shop_id, partner_key):
    """Tạo HMAC-SHA256 sign theo spec Shopee Open API v2."""
    base_string = f"{partner_id}{api_path}{timestamp}{access_token}{shop_id}"
    return hmac.new(
        partner_key.encode('utf-8'),
        base_string.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def _build_signed_params(creds, api_path, extra=None):
    """Tạo dict params chung đã có sign cho một API call."""
    ts = int(time.time())
    sign = generate_sign(
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
    }
    if extra:
        params.update(extra)
    return params


def _do_get(api_path, params, timeout=30):
    """Thực hiện HTTP GET và trả về (status_code, body_dict)."""
    url = f"{SHOPEE_BASE_URL}{api_path}"
    try:
        resp = req_lib.get(url, params=params, timeout=timeout)
    except Exception as e:
        raise UserError(_("Lỗi kết nối tới Shopee API:\n%s") % str(e))
    try:
        body = resp.json()
    except Exception:
        raise UserError(_("Shopee trả về response không hợp lệ:\n%s") % resp.text)
    return resp.status_code, body


# ──────────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────────

def get_credentials_from_shop(shop):
    """
    Đọc credentials từ shopee.shop record.
    Trả về dict {'partner_id', 'partner_key', 'access_token', 'shop_identifier'}.
    Raise UserError nếu thiếu thông tin.
    """
    access_token = getattr(shop, 'access_token', False)
    shop_identifier = getattr(shop, 'shop_identifier', False)

    account = getattr(shop, 'account_id', False)
    if not account:
        raise UserError(
            _("Shop '%s' chưa được liên kết với Shopee Account.") % shop.display_name
        )

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


def get_credentials_from_wizard(wizard):
    """
    Đọc credentials từ shopee.order.fetch.wizard record (chọn shop_id trên wizard).
    Raise UserError nếu chưa chọn shop hoặc thiếu thông tin.
    """
    shop = wizard.shop_id
    if not shop:
        raise UserError(_("Vui lòng chọn Shop Shopee."))
    return get_credentials_from_shop(shop)


def call_order_detail(creds, order_sn_list_str, optional_fields=None):
    """
    Gọi Shopee get_order_detail API.
    Trả về (status_code, body_dict, params_sent).

    :param creds: dict credentials từ get_credentials_*()
    :param order_sn_list_str: chuỗi mã đơn cách nhau bởi dấu phẩy
    :param optional_fields: chuỗi optional fields (None = dùng DEFAULT)
    """
    api_path = '/api/v2/order/get_order_detail'
    extra = {'order_sn_list': order_sn_list_str}

    fields = optional_fields or DEFAULT_OPTIONAL_FIELDS
    if isinstance(fields, str):
        fields = ','.join(f.strip() for f in fields.split(',') if f.strip())
    if fields:
        extra['response_optional_fields'] = fields

    params = _build_signed_params(creds, api_path, extra)
    _logger.info("Shopee API get_order_detail – params: %s", {k: v for k, v in params.items() if k != 'sign'})
    status_code, body = _do_get(api_path, params)
    return status_code, body, params


def call_escrow_detail(creds, order_sn):
    """
    Gọi Shopee get_escrow_detail API.
    Trả về dict response (bên trong key 'response') hoặc None nếu lỗi.

    :param creds: dict credentials
    :param order_sn: mã đơn hàng Shopee
    """
    api_path = '/api/v2/payment/get_escrow_detail'
    params = _build_signed_params(creds, api_path, {'order_sn': order_sn})
    _logger.info("Shopee API get_escrow_detail – order_sn=%s", order_sn)

    try:
        _status, body = _do_get(api_path, params)
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


def call_escrow_detail_strict(creds, order_sn):
    """
    Gọi Shopee get_escrow_detail API — raise UserError thay vì trả None.
    Dùng khi bắt buộc phải có dữ liệu escrow (ví dụ từ nút trực tiếp trên form đơn hàng).
    """
    api_path = '/api/v2/payment/get_escrow_detail'
    params = _build_signed_params(creds, api_path, {'order_sn': order_sn})
    _logger.info("Shopee API get_escrow_detail (strict) – order_sn=%s", order_sn)

    try:
        _status, body = _do_get(api_path, params)
    except Exception as e:
        raise UserError(_("Lỗi gọi Shopee Escrow API cho %s:\n%s") % (order_sn, str(e)))

    if body.get('error'):
        raise UserError(
            _("Shopee Escrow API lỗi cho %s:\n%s - %s")
            % (order_sn, body.get('error'), body.get('message'))
        )

    return body.get('response', {})
