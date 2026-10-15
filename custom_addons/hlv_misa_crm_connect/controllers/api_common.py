# -*- coding: utf-8 -*-
"""Khung chung của mọi route /api/misa-crm/*: bật/tắt, kiểm key, đọc body, đổi lỗi thành JSON.

Cùng quy ước với /api/misa/product/* (misa_fetch_po_button/controllers/misa_product_api.py):
kết quả luôn có ``ok``; lỗi có ``error`` (mã máy đọc) và ``message`` (người đọc).
"""
import logging

from odoo.addons.misa_fetch_po_button.controllers.misa_product_api import ApiError, _reply
from odoo.addons.misa_fetch_po_button.utils.api_key import api_key_matches
from odoo.exceptions import UserError
from odoo.http import request

from ..models.misa_crm_client import CrmInputError, MisaCrmError
from ..models.res_config_settings import PARAM_ALLOW_WRITE, PARAM_ENABLED, PARAM_KEY

_logger = logging.getLogger(__name__)


def _guard(write):
    """Raise ApiError nếu API đang tắt / key thiếu, sai / route ghi mà chưa cho ghi. Không log key."""
    params = request.env["ir.config_parameter"].sudo()
    if not params.get_param(PARAM_ENABLED):
        raise ApiError(503, "disabled", "API MISA CRM đang tắt (Cài đặt → Tồn kho → API MISA CRM).")
    expected = params.get_param(PARAM_KEY)
    if not (expected or "").strip():
        raise ApiError(503, "not_configured", "Odoo chưa tạo API key cho API MISA CRM.")
    provided = request.httprequest.headers.get("X-API-Key")
    if not provided:
        raise ApiError(401, "missing_key", "Thiếu header X-API-Key.")
    if not api_key_matches(provided, expected):
        _logger.warning("MISA_CRM_API sai key từ %s", request.httprequest.remote_addr)
        raise ApiError(403, "invalid_key", "API key không hợp lệ.")
    if write and not params.get_param(PARAM_ALLOW_WRITE):
        raise ApiError(403, "write_disabled", "API MISA CRM đang chỉ cho tra cứu, chưa cho tạo dữ liệu.")


def _body():
    """Body JSON object; body rỗng -> {} (route không cần tham số vẫn gọi được không body)."""
    if not request.httprequest.get_data():
        return {}
    try:
        data = request.get_json_data()
    except ValueError:
        raise ApiError(400, "invalid_json", "Body phải là JSON hợp lệ.")
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_json", "Body phải là một object JSON.")
    return data


def int_field(data, key, required=True, default=None):
    """Số nguyên trong body. Thiếu: required -> 400, không thì ``default``. Sai kiểu -> 400."""
    value = data.get(key)
    if value in (None, ""):
        if required:
            raise ApiError(400, "missing_field", "Thiếu trường '%s'." % key)
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(400, "invalid_field", "Trường '%s' phải là số nguyên." % key)


def handle(action, work, write=False):
    """Chạy ``work(body, connector)`` sau khi qua ``_guard``; trả JSON ``{"ok": true, ...}``."""
    try:
        _guard(write)
        result = work(_body(), request.env["hlv.misa.crm.connect"].sudo())
        if write:
            _logger.info("MISA_CRM_API %s từ %s: %s", action, request.httprequest.remote_addr, result)
        return _reply(dict(result, ok=True))
    except ApiError as error:
        return _reply(dict(error.extra, ok=False, error=error.error, message=error.message), status=error.status)
    except CrmInputError as error:
        return _reply({"ok": False, "error": error.error, "message": error.message}, status=error.status)
    except (MisaCrmError, UserError) as error:
        # UserError: hàm đọc dùng lại của misa_fetch_po_button báo "Không gọi được MISA CRM: …".
        return _reply({"ok": False, "error": "misa_error", "message": str(error)}, status=502)
    except Exception as error:  # noqa: BLE001 — lỗi mạng / MISA lạ: báo bên gọi, ghi log đủ để soi
        _logger.exception("MISA_CRM_API %s lỗi", action)
        return _reply({"ok": False, "error": "misa_error", "message": str(error)}, status=502)
