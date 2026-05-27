# -*- coding: utf-8 -*-
"""
services/shopee_product_api.py

Toàn bộ logic giao tiếp với Shopee Open API v2 — nhóm Product.

Tái sử dụng auth/signing từ shopee_order_fetch.services.shopee_api.
Không phụ thuộc vào bất kỳ model Odoo nào — chỉ nhận dict credentials.

APIs được implement:
  GET  /api/v2/product/get_category
  GET  /api/v2/product/get_attribute_tree
  GET  /api/v2/product/get_brand_list
  GET  /api/v2/product/get_item_limit
  GET  /api/v2/product/get_item_list
  GET  /api/v2/product/get_item_base_info
  GET  /api/v2/product/get_item_extra_info
  POST /api/v2/product/add_item
  POST /api/v2/product/update_item
  POST /api/v2/product/delete_item
    GET  /api/v2/product/get_comment
    POST /api/v2/product/reply_comment
    GET  /api/v2/product/get_boosted_list
    GET  /api/v2/product/get_item_violation_info
    GET  /api/v2/product/get_size_chart_list
    GET  /api/v2/product/get_size_chart_detail
    POST /api/v2/product/generate_kit_image
"""
import json
import logging

import requests as req_lib

from odoo.exceptions import UserError
from odoo.addons.shopee_order_fetch.services.shopee_api import (
    _build_signed_params,
    SHOPEE_BASE_URL,
)

_logger = logging.getLogger(__name__)

# Shopee cho phép tối đa 50 item_id mỗi lần gọi get_item_base_info
ITEM_BATCH_SIZE = 50


# ──────────────────────────────────────────────────────
#  HTTP helpers
# ──────────────────────────────────────────────────────

def _do_get(api_path, params, timeout=30):
    url = f"{SHOPEE_BASE_URL}{api_path}"
    try:
        resp = req_lib.get(url, params=params, timeout=timeout)
    except Exception as e:
        raise UserError("lỗi kết nối Shopee API:\n%s" % str(e))
    try:
        body = resp.json()
    except Exception:
        raise UserError("Shopee trả về response không hợp lệ:\n%s" % resp.text)
    return resp.status_code, body


def _do_post(api_path, params, json_body, timeout=30):
    url = f"{SHOPEE_BASE_URL}{api_path}"
    try:
        resp = req_lib.post(url, params=params, json=json_body, timeout=timeout)
    except Exception as e:
        raise UserError("lỗi kết nối Shopee API:\n%s" % str(e))
    try:
        body = resp.json()
    except Exception:
        raise UserError("Shopee trả về response không hợp lệ:\n%s" % resp.text)
    return resp.status_code, body


def _check_error(body, context=''):
    """Raise UserError nếu response có field error."""
    if body.get('error'):
        raise UserError(
            "Shopee API lỗi%s: %s — %s"
            % (f" ({context})" if context else '', body.get('error'), body.get('message', ''))
        )


# ──────────────────────────────────────────────────────
#  Reference data (không yêu cầu shop-level auth)
# ──────────────────────────────────────────────────────

def call_get_category(creds, language='vi'):
    """
    GET /api/v2/product/get_category

    Trả về list category_list.
    Mỗi item: {category_id, parent_category_id, original_category_name,
               display_category_name, has_children}
    """
    api_path = '/api/v2/product/get_category'
    params = _build_signed_params(creds, api_path, {'language': language})
    _logger.info("Shopee Product API: get_category lang=%s", language)
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_category')
    return body.get('response', {}).get('category_list', [])


def call_get_attribute_tree(creds, category_id, language='vi'):
    """
    GET /api/v2/product/get_attribute_tree

    Trả về list attribute_list cho category_id chỉ định.
    Mỗi attribute: {attribute_id, original_attribute_name, is_mandatory,
                    input_type, attribute_value_list}
    """
    api_path = '/api/v2/product/get_attribute_tree'
    extra = {
        'category_id': category_id,
        'language': language,
    }
    params = _build_signed_params(creds, api_path, extra)
    _logger.info("Shopee Product API: get_attribute_tree category_id=%s", category_id)
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_attribute_tree')
    return body.get('response', {}).get('attribute_list', [])


def call_get_brand_list(creds, category_id, status=1, offset=0, page_size=100):
    """
    GET /api/v2/product/get_brand_list

    status: 1=normal brands, 2=brand đang chờ review
    Trả về (brand_list, has_next_page, next_offset).
    Mỗi brand: {brand_id, original_brand_name, brand_logo}
    """
    api_path = '/api/v2/product/get_brand_list'
    extra = {
        'category_id': category_id,
        'status': status,
        'offset': offset,
        'page_size': page_size,
    }
    params = _build_signed_params(creds, api_path, extra)
    _logger.info("Shopee Product API: get_brand_list category_id=%s offset=%s", category_id, offset)
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_brand_list')
    resp = body.get('response', {})
    return (
        resp.get('brand_list', []),
        resp.get('has_next_page', False),
        resp.get('next_offset', 0),
    )


def call_get_item_limit(creds):
    """
    GET /api/v2/product/get_item_limit

    Trả về dict response (giới hạn số sản phẩm của shop).
    Các key: normal_item_limit, pre_order_item_limit, ...
    """
    api_path = '/api/v2/product/get_item_limit'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: get_item_limit")
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_item_limit')
    return body.get('response', {})


# ──────────────────────────────────────────────────────
#  Read items
# ──────────────────────────────────────────────────────

def call_get_item_list(creds, item_status=None, page_size=100, offset=0,
                       update_time_from=None, update_time_to=None):
    """
    GET /api/v2/product/get_item_list

    item_status: list of str, e.g. ['NORMAL', 'UNLIST'] — BẮT BUỘC theo Shopee.
    page_size: tối đa 100.

    Trả về (item_list, total_count, has_next_page, next_offset).
    item_list gồm các dict {item_id, item_status, update_time}.
    """
    if not item_status:
        item_status = ['NORMAL']

    api_path = '/api/v2/product/get_item_list'
    extra = {
        'offset': offset,
        'page_size': page_size,
        # Shopee yêu cầu repeated params: item_status=NORMAL&item_status=BANNED
        'item_status': item_status,
    }
    if update_time_from:
        extra['update_time_from'] = update_time_from
    if update_time_to:
        extra['update_time_to'] = update_time_to

    params = _build_signed_params(creds, api_path, extra)
    _logger.info(
        "Shopee Product API: get_item_list status=%s offset=%s page_size=%s",
        item_status, offset, page_size,
    )
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_item_list')
    resp = body.get('response')
    if not isinstance(resp, dict):
        # Shopee đôi khi trả 'response' là string/null khi lỗi auth/quota
        raise UserError(
            "Shopee get_item_list: phản hồi không hợp lệ — %s"
            % (body.get('message', '') or str(resp or 'null'))
        )
    return (
        resp.get('item', []),
        resp.get('total_count', 0),
        resp.get('has_next_page', False),
        resp.get('next_offset', 0),
    )


def call_get_item_list_all(creds, item_status=None, update_time_from=None,
                           update_time_to=None, page_size=100):
    """
    Convenience wrapper: gọi get_item_list nhiều lần cho đến hết.

    Trả về list tất cả item dict {item_id, item_status, update_time}.
    """
    all_items = []
    offset = 0
    while True:
        items, total, has_next, next_offset = call_get_item_list(
            creds,
            item_status=item_status,
            page_size=page_size,
            offset=offset,
            update_time_from=update_time_from,
            update_time_to=update_time_to,
        )
        all_items.extend(items)
        if not has_next:
            break
        offset = next_offset
    _logger.info("Shopee Product API: get_item_list_all total=%d", len(all_items))
    return all_items


def call_get_item_base_info(creds, item_id_list):
    """
    GET /api/v2/product/get_item_base_info

    item_id_list: list of int, tối đa 50 mỗi lần gọi.
    Shopee nhận tham số dưới dạng JSON array trong URL: item_id_list=[id1,id2,...]

    Trả về list item dict đầy đủ.
    """
    api_path = '/api/v2/product/get_item_base_info'
    # Shopee yêu cầu JSON array string trong query param
    extra = {'item_id_list': json.dumps(item_id_list)}
    params = _build_signed_params(creds, api_path, extra)
    _logger.info(
        "Shopee Product API: get_item_base_info ids_count=%d first=%s",
        len(item_id_list), item_id_list[:3],
    )
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_item_base_info')
    resp = body.get('response')
    if not isinstance(resp, dict):
        raise UserError(
            "Shopee get_item_base_info: phản hồi không hợp lệ — %s"
            % (body.get('message', '') or str(resp or 'null'))
        )
    return resp.get('item_list', [])


def call_get_item_base_info_batch(creds, item_id_list):
    """
    Convenience wrapper: tự động chia batch 50 item.

    Trả về list item dict đầy đủ (ghép từ nhiều batch).
    """
    results = []
    for i in range(0, len(item_id_list), ITEM_BATCH_SIZE):
        batch = item_id_list[i: i + ITEM_BATCH_SIZE]
        results.extend(call_get_item_base_info(creds, batch))
    return results


def call_get_item_extra_info(creds, item_id_list):
    """
    GET /api/v2/product/get_item_extra_info

    item_id_list: list of int, tối đa 50.
    Trả về list item extra info (commission, sold count, ...).
    Lỗi không raise — trả về [] để caller bỏ qua nếu không cần thiết.
    """
    api_path = '/api/v2/product/get_item_extra_info'
    extra = {'item_id_list': json.dumps(item_id_list)}
    params = _build_signed_params(creds, api_path, extra)
    _logger.info("Shopee Product API: get_item_extra_info ids_count=%d", len(item_id_list))
    try:
        _status, body = _do_get(api_path, params)
    except Exception as e:
        _logger.warning("Shopee get_item_extra_info thất bại: %s", str(e))
        return []
    if body.get('error'):
        _logger.warning(
            "Shopee get_item_extra_info lỗi: %s - %s",
            body.get('error'), body.get('message'),
        )
        return []
    return body.get('response', {}).get('item_list', [])


# ──────────────────────────────────────────────────────
#  Write items
# ──────────────────────────────────────────────────────

def call_add_item(creds, item_data):
    """
    POST /api/v2/product/add_item

    item_data: dict payload đúng theo Shopee spec (category_id, item_name,
               description, item_sku, price_info, stock_info_v2, ...).

    Trả về response dict {item_id, ...}.
    """
    api_path = '/api/v2/product/add_item'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: add_item sku=%s", item_data.get('item_sku', '?'))
    _status, body = _do_post(api_path, params, item_data)
    _check_error(body, 'add_item')
    return body.get('response', {})


def call_update_item(creds, item_id, item_data):
    """
    POST /api/v2/product/update_item

    item_id: int — Shopee item_id
    item_data: dict với các field muốn cập nhật (chỉ gửi field cần thay đổi).

    Trả về response dict.
    """
    api_path = '/api/v2/product/update_item'
    params = _build_signed_params(creds, api_path)
    payload = dict(item_data, item_id=item_id)
    _logger.info("Shopee Product API: update_item item_id=%s", item_id)
    _status, body = _do_post(api_path, params, payload)
    _check_error(body, 'update_item')
    return body.get('response', {})


def call_delete_item(creds, item_id_list):
    """
    POST /api/v2/product/delete_item

    item_id_list: list of int.
    Trả về response dict (có thể có failure_list).
    """
    api_path = '/api/v2/product/delete_item'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: delete_item ids=%s", item_id_list)
    _status, body = _do_post(api_path, params, {'item_id_list': item_id_list})
    _check_error(body, 'delete_item')
    return body.get('response', {})


# ──────────────────────────────────────────────────────
#  Tier Variation & Model management
# ──────────────────────────────────────────────────────

def call_get_model_list(creds, item_id):
    """
    GET /api/v2/product/get_model_list

    Trả về (model_list, tier_variation_list).
    model_list: [{model_id, tier_index, model_sku, model_status, price_info, stock_info_v2, ...}]
    tier_variation_list: [{name, option_list}]
    """
    api_path = '/api/v2/product/get_model_list'
    params = _build_signed_params(creds, api_path, {'item_id': item_id})
    _logger.info("Shopee Product API: get_model_list item_id=%s", item_id)
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_model_list')
    resp = body.get('response', {})
    return resp.get('model', []), resp.get('tier_variation', [])


def call_init_tier_variation(creds, payload):
    """
    POST /api/v2/product/init_tier_variation

    payload bao gồm:
      item_id, standardise_tier_variation (list), model (list).
    Dùng để khởi tạo hoặc thay đổi cấu trúc tier variation của sản phẩm.
    Hỗ trợ: no tier ↔ 1 tier ↔ 2 tier.

    Trả về response dict {item_id, tier_variation, model}.
    """
    api_path = '/api/v2/product/init_tier_variation'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: init_tier_variation item_id=%s", payload.get('item_id'))
    _status, body = _do_post(api_path, params, payload)
    _check_error(body, 'init_tier_variation')
    return body.get('response', {})


def call_update_tier_variation(creds, payload):
    """
    POST /api/v2/product/update_tier_variation

    Cập nhật tier variation (thêm option, sửa tên option...) mà không thay đổi cấu trúc.
    payload tương tự init_tier_variation.

    Trả về response dict.
    """
    api_path = '/api/v2/product/update_tier_variation'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: update_tier_variation item_id=%s", payload.get('item_id'))
    _status, body = _do_post(api_path, params, payload)
    _check_error(body, 'update_tier_variation')
    return body.get('response', {})


def call_add_model(creds, item_id, model_list):
    """
    POST /api/v2/product/add_model

    Thêm model mới vào sản phẩm đã có tier variation.
    model_list: list of {tier_index, model_sku, original_price, seller_stock}.

    Trả về response dict {model}.
    """
    api_path = '/api/v2/product/add_model'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: add_model item_id=%s count=%d", item_id, len(model_list))
    _status, body = _do_post(api_path, params, {'item_id': item_id, 'model': model_list})
    _check_error(body, 'add_model')
    return body.get('response', {})


def call_update_model(creds, item_id, model_list):
    """
    POST /api/v2/product/update_model

    Cập nhật thông tin model (SKU, giá, tồn kho, cân nặng...).
    model_list: list of {model_id, model_sku, original_price, seller_stock, ...}.

    Trả về response dict.
    """
    api_path = '/api/v2/product/update_model'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: update_model item_id=%s count=%d", item_id, len(model_list))
    _status, body = _do_post(api_path, params, {'item_id': item_id, 'model': model_list})
    _check_error(body, 'update_model')
    return body.get('response', {})


def call_delete_model(creds, item_id, model_id_list):
    """
    POST /api/v2/product/delete_model

    Xóa model khỏi sản phẩm.
    model_id_list: list of int (Shopee model_id).

    Trả về response dict.
    """
    api_path = '/api/v2/product/delete_model'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: delete_model item_id=%s model_ids=%s", item_id, model_id_list)
    _status, body = _do_post(api_path, params, {'item_id': item_id, 'model_id_list': model_id_list})
    _check_error(body, 'delete_model')
    return body.get('response', {})


# ──────────────────────────────────────────────────────
#  Price & Stock update
# ──────────────────────────────────────────────────────

def call_update_price(creds, item_id, price_list):
    """
    POST /api/v2/product/update_price

    Cập nhật giá cho một item (tối đa 50 model mỗi lần gọi).
    price_list: [{model_id: int, original_price: float}, ...]
      - model_id = 0 cho sản phẩm không có biến thể.

    Trả về (success_list, failure_list).
    """
    api_path = '/api/v2/product/update_price'
    params = _build_signed_params(creds, api_path)
    _logger.info(
        "Shopee Product API: update_price item_id=%s entries=%d", item_id, len(price_list)
    )
    _status, body = _do_post(api_path, params, {'item_id': item_id, 'price_list': price_list})
    _check_error(body, 'update_price')
    resp = body.get('response', {})
    return resp.get('success_list', []), resp.get('failure_list', [])


def call_update_stock(creds, item_id, stock_list):
    """
    POST /api/v2/product/update_stock

    Cập nhật tồn kho seller cho một item (tối đa 50 model mỗi lần gọi).
    stock_list: [{model_id: int, seller_stock: [{stock: int}]}, ...]
      - model_id = 0 cho sản phẩm không có biến thể.

    Trả về (success_list, failure_list).
    """
    api_path = '/api/v2/product/update_stock'
    params = _build_signed_params(creds, api_path)
    _logger.info(
        "Shopee Product API: update_stock item_id=%s entries=%d", item_id, len(stock_list)
    )
    _status, body = _do_post(api_path, params, {'item_id': item_id, 'stock_list': stock_list})
    _check_error(body, 'update_stock')
    resp = body.get('response', {})
    return resp.get('success_list', []), resp.get('failure_list', [])


def call_get_boosted_list(creds):
    """
    GET /api/v2/product/get_boosted_list

    Trả về danh sách item đang boost cùng thời gian cooldown còn lại.
    """
    api_path = '/api/v2/product/get_boosted_list'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: get_boosted_list")
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_boosted_list')
    response = body.get('response', {})
    if not isinstance(response, dict):
        return []
    item_list = response.get('item_list', [])
    return item_list if isinstance(item_list, list) else []


def call_get_comment(creds, item_id=None, comment_id=None, cursor='', page_size=10):
    """
    GET /api/v2/product/get_comment

    Lấy bình luận theo item_id hoặc comment_id. page_size: 1..100.
    Trả về response dict gồm item_comment_list, more, next_cursor.
    """
    api_path = '/api/v2/product/get_comment'
    extra = {'cursor': cursor or '', 'page_size': page_size}
    if item_id:
        extra['item_id'] = item_id
    if comment_id:
        extra['comment_id'] = comment_id
    params = _build_signed_params(creds, api_path, extra)
    _logger.info("Shopee Product API: get_comment item_id=%s comment_id=%s", item_id, comment_id)
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_comment')
    response = body.get('response', {})
    return response if isinstance(response, dict) else {}


def call_reply_comment(creds, comment_list):
    """
    POST /api/v2/product/reply_comment

    comment_list: [{comment_id: int, comment: str}], giới hạn 1..100.
    """
    api_path = '/api/v2/product/reply_comment'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: reply_comment count=%d", len(comment_list))
    _status, body = _do_post(api_path, params, {'comment_list': comment_list})
    _check_error(body, 'reply_comment')
    response = body.get('response', {})
    return response if isinstance(response, dict) else {}


def call_get_item_violation_info(creds, item_id_list):
    """
    GET /api/v2/product/get_item_violation_info

    item_id_list: list[int], tối đa 50.
    """
    api_path = '/api/v2/product/get_item_violation_info'
    extra = {'item_id_list': json.dumps(item_id_list)}
    params = _build_signed_params(creds, api_path, extra)
    _logger.info("Shopee Product API: get_item_violation_info count=%d", len(item_id_list))
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_item_violation_info')
    response = body.get('response', {})
    if not isinstance(response, dict):
        return []
    item_list = response.get('item_list', [])
    return item_list if isinstance(item_list, list) else []


def call_get_size_chart_list(creds, category_id, page_size=10, cursor=''):
    """
    GET /api/v2/product/get_size_chart_list

    Lấy danh sách size chart theo category_id. page_size tối đa 50.
    """
    api_path = '/api/v2/product/get_size_chart_list'
    extra = {'category_id': category_id, 'page_size': page_size}
    if cursor:
        extra['cursor'] = cursor
    params = _build_signed_params(creds, api_path, extra)
    _logger.info("Shopee Product API: get_size_chart_list category_id=%s", category_id)
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_size_chart_list')
    response = body.get('response', {})
    return response if isinstance(response, dict) else {}


def call_get_size_chart_detail(creds, size_chart_id):
    """
    GET /api/v2/product/get_size_chart_detail

    Lấy chi tiết size chart theo size_chart_id.
    """
    api_path = '/api/v2/product/get_size_chart_detail'
    params = _build_signed_params(creds, api_path, {'size_chart_id': size_chart_id})
    _logger.info("Shopee Product API: get_size_chart_detail size_chart_id=%s", size_chart_id)
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_size_chart_detail')
    response = body.get('response', {})
    return response if isinstance(response, dict) else {}


def call_generate_kit_image(creds, component_list):
    """
    POST /api/v2/product/generate_kit_image

    component_list: [{component_item_id: int, component_model_id?: int}], tối đa 9.
    """
    api_path = '/api/v2/product/generate_kit_image'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: generate_kit_image count=%d", len(component_list))
    _status, body = _do_post(api_path, params, {'component_list': component_list})
    _check_error(body, 'generate_kit_image')
    response = body.get('response', {})
    return response if isinstance(response, dict) else {}


# ---------------------------------------------------------------------------
# Search & Recommendation APIs
# ---------------------------------------------------------------------------

def call_search_item(creds, item_name=None, item_sku=None, item_status=None,
                     attribute_status=None, deboost_only=None,
                     page_size=10, offset=''):
    """
    GET /api/v2/product/search_item

    Tìm kiếm sản phẩm theo tên, SKU, trạng thái hoặc trạng thái attribute.
    Ít nhất một trong item_name hoặc attribute_status phải được cung cấp (trừ khi item_sku).
    Phân trang qua offset (string, nhận từ next_offset của response trước).

    Trả về (item_id_list, total_count, next_offset).
    """
    api_path = '/api/v2/product/search_item'
    extra = {'page_size': page_size}
    if offset:
        extra['offset'] = offset
    if item_name:
        extra['item_name'] = item_name
    if item_sku:
        extra['item_sku'] = item_sku
    if attribute_status is not None:
        extra['attribute_status'] = attribute_status
    if deboost_only is not None:
        extra['deboost_only'] = deboost_only
    if item_status:
        # Có thể là list hoặc string
        if isinstance(item_status, (list, tuple)):
            extra['item_status'] = item_status
        else:
            extra['item_status'] = [item_status]
    params = _build_signed_params(creds, api_path, extra)
    _logger.info("Shopee Product API: search_item name=%r sku=%r", item_name, item_sku)
    _status, body = _do_get(api_path, params)
    _check_error(body, 'search_item')
    resp = body.get('response', {})
    return (
        resp.get('item_id_list', []),
        resp.get('total_count', 0),
        resp.get('next_offset', ''),
    )


def call_category_recommend(creds, item_name, product_cover_image=None):
    """
    GET /api/v2/product/category_recommend

    Gợi ý danh mục Shopee dựa trên tên sản phẩm và ảnh bìa.
    Trả về danh sách category_id được gợi ý.
    """
    api_path = '/api/v2/product/category_recommend'
    extra = {'item_name': item_name}
    if product_cover_image:
        extra['product_cover_image'] = product_cover_image
    params = _build_signed_params(creds, api_path, extra)
    _logger.info("Shopee Product API: category_recommend item_name=%r", item_name)
    _status, body = _do_get(api_path, params)
    _check_error(body, 'category_recommend')
    return body.get('response', {}).get('category_id', [])


def call_register_brand(creds, payload):
    """
    POST /api/v2/product/register_brand

    Đăng ký thương hiệu mới trên Shopee.
    payload bắt buộc: original_brand_name, category_list, product_image (image_id_list), brand_region.
    payload tùy chọn: app_logo_image_id, pc_logo_image_id, brand_website,
      brand_description, additional_information, licenses.
    Trả về (brand_id, original_brand_name).
    """
    api_path = '/api/v2/product/register_brand'
    params = _build_signed_params(creds, api_path)
    _logger.info(
        "Shopee Product API: register_brand name=%r", payload.get('original_brand_name')
    )
    _status, body = _do_post(api_path, params, payload)
    _check_error(body, 'register_brand')
    resp = body.get('response', {})
    return resp.get('brand_id'), resp.get('original_brand_name')


def call_get_recommend_attribute(creds, item_name, category_id, cover_image_id=None):
    """
    GET /api/v2/product/get_recommend_attribute

    Lấy danh sách attribute được gợi ý khi tạo sản phẩm mới.
    Trả về attribute_list (list of dict: attribute_id, attribute_value_list, ...).
    """
    api_path = '/api/v2/product/get_recommend_attribute'
    extra = {'item_name': item_name, 'category_id': category_id}
    if cover_image_id is not None:
        extra['cover_image_id'] = cover_image_id
    params = _build_signed_params(creds, api_path, extra)
    _logger.info(
        "Shopee Product API: get_recommend_attribute category_id=%s", category_id
    )
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_recommend_attribute')
    return body.get('response', {}).get('attribute_list', [])


# ---------------------------------------------------------------------------
# Weight / Variation helpers
# ---------------------------------------------------------------------------

def call_get_weight_recommendation(creds, payload):
    """
    POST /api/v2/product/get_weight_recommendation

    Gợi ý khoảng cân nặng cho sản phẩm (hiện chỉ áp dụng cho shop BR).
    payload phải bao gồm: item_name, cover_image_id, category_id,
      attribute_list, brand_id, description_type, (description_info | description).
    Trả về normal_weight_range (list[float], VD: [0.1, 0.5]).
    """
    api_path = '/api/v2/product/get_weight_recommendation'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: get_weight_recommendation")
    _status, body = _do_post(api_path, params, payload)
    _check_error(body, 'get_weight_recommendation')
    return body.get('response', {}).get('normal_weight_range', [])


def call_get_variations(creds, category_id):
    """
    GET /api/v2/product/get_variation_tree

    Lấy cây biến thể chuẩn (standardized tier variation) của Shopee theo category.
    Trả về standardise_variation_list (3-layer tree: variation → group → option).
    """
    api_path = '/api/v2/product/get_variation_tree'
    extra = {'category_id': category_id}
    params = _build_signed_params(creds, api_path, extra)
    _logger.info("Shopee Product API: get_variations category_id=%s", category_id)
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_variations')
    return body.get('data', {}).get('standardise_variation_list', [])


# ---------------------------------------------------------------------------
# Content Diagnosis APIs
# ---------------------------------------------------------------------------

def call_get_item_content_diagnosis_result(creds, item_id_list):
    """
    POST /api/v2/product/get_item_content_diagnosis_result

    Lấy kết quả chẩn đoán nội dung (quality level + unfinished tasks) cho danh sách item.
    item_id_list: list[int], tối đa 48 item mỗi lần.
    Trả về (success_item_list, failure_item_list).
      success: [{item_id, quality_level, unfinished_task: [{issue_type, suggestion}]}, ...]
      failure: [{item_id, failed_reason}, ...]
    """
    api_path = '/api/v2/product/get_item_content_diagnosis_result'
    params = _build_signed_params(creds, api_path)
    _logger.info(
        "Shopee Product API: get_item_content_diagnosis_result count=%d", len(item_id_list)
    )
    _status, body = _do_post(api_path, params, {'item_id_list': item_id_list})
    _check_error(body, 'get_item_content_diagnosis_result')
    resp = body.get('response', {})
    return resp.get('success_item_list', []), resp.get('failure_item_list', [])


def call_get_item_list_by_content_diagnosis(creds, page_size=20, offset='',
                                            quality_level=None, issue_type=None):
    """
    POST /api/v2/product/get_item_list_by_content_diagnosis

    Lấy danh sách sản phẩm và chi tiết chất lượng nội dung theo quality_level / issue_type.
    quality_level: list[int] — 1=TO_BE_IMPROVED, 2=QUALIFIED, 3=EXCELLENT
    issue_type: list[int] — 1–11 (xem docs)
    Trả về (item_list, total_count, has_next_page, next_offset).
    """
    api_path = '/api/v2/product/get_item_list_by_content_diagnosis'
    payload = {'page_size': page_size}
    if offset:
        payload['offset'] = offset
    if quality_level:
        payload['quality_level'] = quality_level
    if issue_type:
        payload['issue_type'] = issue_type
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: get_item_list_by_content_diagnosis page_size=%d", page_size)
    _status, body = _do_post(api_path, params, payload)
    _check_error(body, 'get_item_list_by_content_diagnosis')
    resp = body.get('response', {})
    return (
        resp.get('item_list', []),
        resp.get('total_count', 0),
        resp.get('has_next_page', False),
        resp.get('next_offset', ''),
    )


# ---------------------------------------------------------------------------
# Kit Item APIs
# ---------------------------------------------------------------------------

def call_get_kit_item_limit(creds, category_id=None):
    """
    GET /api/v2/product/get_kit_item_limit

    Lấy giới hạn (price, image count, description, tier variation, ...) cho kit item.
    category_id: tùy chọn — leaf category id.
    Trả về response dict chứa price_limit, item_name_length_limit, component_count_limit_of_single_model, ...
    """
    api_path = '/api/v2/product/get_kit_item_limit'
    extra = {}
    if category_id is not None:
        extra['category_id'] = category_id
    params = _build_signed_params(creds, api_path, extra)
    _logger.info("Shopee Product API: get_kit_item_limit category_id=%s", category_id)
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_kit_item_limit')
    return body.get('response', {})


def call_add_kit_item(creds, payload):
    """
    POST /api/v2/product/add_kit_item

    Tạo kit item mới bằng cách ghép nhiều sản phẩm thành một combo.
    payload phải bao gồm: item_setting (item_name, images, description_type,
      logistic_info, weight, model_list, tier_variation_list).
    Tham khảo docs để biết cấu trúc đầy đủ.
    Trả về item_id của kit item vừa tạo.
    """
    api_path = '/api/v2/product/add_kit_item'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: add_kit_item")
    _status, body = _do_post(api_path, params, payload)
    _check_error(body, 'add_kit_item')
    return body.get('response', {}).get('item_id')


def call_update_kit_item(creds, item_id, payload):
    """
    POST /api/v2/product/update_kit_item

    Cập nhật thông tin kit item (chỉ hỗ trợ thêm biến thể và cập nhật ảnh/giá/SKU
    của biến thể đã có; không hỗ trợ xóa biến thể hay thay đổi items/quantity).
    payload: dict — item_setting (tùy chọn) + model_list (tùy chọn) + sync_setting (tùy chọn).
    Tham khảo docs để biết giới hạn cập nhật.
    """
    api_path = '/api/v2/product/update_kit_item'
    params = _build_signed_params(creds, api_path)
    _logger.info("Shopee Product API: update_kit_item item_id=%s", item_id)
    data = dict(payload)
    data['item_id'] = item_id
    _status, body = _do_post(api_path, params, data)
    _check_error(body, 'update_kit_item')
    return body.get('response', {})


def call_get_kit_item_info(creds, item_id):
    """
    GET /api/v2/product/get_kit_item_info

    Lấy thông tin chi tiết của kit item và danh sách component.
    Trả về product_info dict (item_id, item_name, model_list, tier_variation_list,
      component_list, attributes, brand_info, images, ...).
    """
    api_path = '/api/v2/product/get_kit_item_info'
    extra = {'item_id': item_id}
    params = _build_signed_params(creds, api_path, extra)
    _logger.info("Shopee Product API: get_kit_item_info item_id=%s", item_id)
    _status, body = _do_get(api_path, params)
    _check_error(body, 'get_kit_item_info')
    return body.get('response', {}).get('product_info', {})
