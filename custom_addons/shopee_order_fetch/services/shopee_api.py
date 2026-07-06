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

# Lỗi Shopee trả về khi access_token hết hạn (typo trong Shopee API — 3 chữ 'e' là đúng)
SHOPEE_INVALID_TOKEN_ERRORS = frozenset([
    'invalid_access_token',
    'invalid_acceess_token',  # typo lịch sử trong Shopee API
    'error_auth',
])

_logger = logging.getLogger(__name__)

SHOPEE_BASE_URL    = 'https://partner.shopeemobile.com'
SHOPEE_SANDBOX_URL = 'https://openplatform.sandbox.test-stable.shopee.sg'

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


def _is_invalid_token_response(body):
    """Return True when Shopee response means access_token must be refreshed."""
    if not isinstance(body, dict):
        return False
    invalid_token_errors = (
        'invalid_access_token',
        'invalid_acceess_token',
        'error_auth',
    )
    text = ' '.join(
        str(body.get(key) or '').lower()
        for key in ('error', 'message', 'debug_message')
    )
    return any(code in text for code in invalid_token_errors)


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

    base_url = SHOPEE_SANDBOX_URL if getattr(shop, 'is_sandbox', False) else SHOPEE_BASE_URL

    return {
        'partner_id': partner_id,
        'partner_key': partner_key,
        'access_token': access_token,
        'shop_identifier': shop_identifier,
        'base_url': base_url,
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


def call_order_detail_with_token_refresh(shop, order_sn_list_str, optional_fields=None):
    """
    Call get_order_detail and refresh access_token once when Shopee rejects it.

    Returns (status_code, body_dict, params_sent, creds_used) so callers can reuse
    the fresh credentials for follow-up API calls such as escrow.
    """
    creds = get_credentials_from_shop(shop)
    status_code, body, params = call_order_detail(creds, order_sn_list_str, optional_fields)
    if not _is_invalid_token_response(body):
        return status_code, body, params, creds

    _logger.warning(
        "Shopee get_order_detail invalid access_token for shop %s - refreshing and retrying once.",
        shop.display_name,
    )
    refresh_shopee_access_token(shop)
    creds = get_credentials_from_shop(shop)
    status_code, body, params = call_order_detail(creds, order_sn_list_str, optional_fields)
    return status_code, body, params, creds


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


# ──────────────────────────────────────────────────────
#  Token Refresh
# ──────────────────────────────────────────────────────

def refresh_shopee_access_token(shop):
    """
    Làm mới Shopee access_token cho một shop record.

    Gọi POST /api/v2/auth/refresh_access_token với refresh_token hiện tại,
    sau đó cập nhật shop.access_token (và shop.refresh_token nếu trả về mới).

    :param shop: shopee.shop record
    :return: new_access_token (str)
    :raises UserError: nếu shop không có refresh_token hoặc Shopee trả lỗi
    """
    refresh_token = getattr(shop, 'refresh_token', False)
    if not refresh_token:
        raise UserError(
            _("Shop '%s' không có Refresh Token — cần cấp quyền OAuth lại từ Shopee.")
            % shop.display_name
        )

    account = getattr(shop, 'account_id', False)
    if not account:
        raise UserError(
            _("Shop '%s' chưa được liên kết với Shopee Account.") % shop.display_name
        )

    partner_id = getattr(account, 'partner_identifier', False)
    partner_key = getattr(account, 'partner_key', False)
    if not partner_id or not partner_key:
        raise UserError(_("Thiếu partner_identifier hoặc partner_key trên Shopee Account."))

    shop_id = getattr(shop, 'shop_identifier', False)
    if not shop_id:
        raise UserError(_("Shop '%s' thiếu shop_identifier.") % shop.display_name)

    api_path = '/api/v2/auth/refresh_access_token'
    ts = int(time.time())
    # Sign cho auth endpoint: KHÔNG có access_token trong base string
    base_string = f"{partner_id}{api_path}{ts}"
    sign = hmac.new(
        str(partner_key).encode('utf-8'),
        base_string.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()

    params = {
        'partner_id': int(partner_id),
        'timestamp': ts,
        'sign': sign,
    }
    body = {
        'refresh_token': refresh_token,
        'shop_id': int(shop_id),
    }

    base_url = SHOPEE_SANDBOX_URL if getattr(shop, 'is_sandbox', False) else SHOPEE_BASE_URL
    url = f"{base_url}{api_path}"

    _logger.info(
        "Shopee: đang refresh access_token cho shop %s (shop_id=%s)",
        shop.display_name, shop_id,
    )
    try:
        resp = req_lib.post(url, params=params, json=body, timeout=30)
        data = resp.json()
    except Exception as exc:
        raise UserError(_("Lỗi kết nối khi refresh Shopee token:\n%s") % str(exc))

    err = data.get('error')
    if err:
        raise UserError(
            _("Shopee từ chối refresh token cho shop '%s':\n%s — %s\n\n"
              "Cần cấp phép OAuth lại từ Shopee Partner Portal.")
            % (shop.display_name, err, data.get('message', ''))
        )

    new_access_token = data.get('access_token')
    new_refresh_token = data.get('refresh_token')

    if not new_access_token:
        raise UserError(_("Shopee không trả về access_token mới sau khi refresh."))

    write_vals = {'access_token': new_access_token}
    if new_refresh_token:
        write_vals['refresh_token'] = new_refresh_token

    shop.sudo().write(write_vals)
    _logger.info(
        "Shopee: refresh token thành công cho shop %s — expire_in=%s",
        shop.display_name, data.get('expire_in', 'N/A'),
    )
    return new_access_token
