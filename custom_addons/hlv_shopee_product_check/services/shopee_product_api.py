# -*- coding: utf-8 -*-
"""Đọc chi tiết sản phẩm / phân loại từ Shopee Open API v2 (nhóm product).

Đi qua ``sale_shopee.utils.make_shopee_api_request`` thay vì tự ký: hàm đó đã lo chữ ký, đúng máy chủ
theo tài khoản, và làm mới access_token trước khi hết hạn — tự ký lại là thêm một chỗ phải sửa khi
Shopee đổi cách xác thực. Hàm đó chỉ biết các thao tác khai trong ``const.API_OPERATIONS_MAPPING``,
nên module này khai thêm hai thao tác đọc sản phẩm (chỉ thêm khoá mới, không đè khoá có sẵn).
"""

from odoo.addons.sale_shopee import const, utils

for _operation, _path in (
    ("get_item_base_info", "/api/v2/product/get_item_base_info"),
    ("get_model_list", "/api/v2/product/get_model_list"),
):
    const.API_OPERATIONS_MAPPING.setdefault(_operation, {"url_path": _path, "api_type": "product"})

# Giới hạn của Shopee: get_item_base_info tối đa 50 id / lần.
BASE_INFO_BATCH = 50


def _response(result):
    """make_shopee_api_request bỏ vỏ ``response`` khi nó có nội dung, giữ nguyên khi rỗng — gỡ cho đều."""
    if isinstance(result, dict) and isinstance(result.get("response"), dict):
        return result["response"]
    return result if isinstance(result, dict) else {}


def get_items_base_info(shop, item_ids):
    """Thông tin cơ bản của tối đa BASE_INFO_BATCH sản phẩm.

    Nhận: shop, list id (chuỗi / int). Trả: list dict ``item_list`` của Shopee; id đã xoá hẳn thì Shopee
    không trả — bên gọi coi id thiếu là "không còn trên Shopee".
    """
    data = _response(utils.make_shopee_api_request(shop, "get_item_base_info", params={
        "item_id_list": ",".join(str(item_id) for item_id in item_ids),
    }))
    return data.get("item_list") or []


def get_model_list(shop, item_id):
    """Danh sách phân loại của một sản phẩm. Trả dict ``{"tier_variation", "model"}`` (có thể rỗng)."""
    return _response(utils.make_shopee_api_request(shop, "get_model_list", params={"item_id": int(item_id)}))
