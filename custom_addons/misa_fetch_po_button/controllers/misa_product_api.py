# -*- coding: utf-8 -*-
"""API cho hệ thống bên ngoài tạo / sửa mã hàng trên MISA CRM qua Odoo.

Odoo giữ tài khoản MISA; bên ngoài chỉ cầm một API key, không bao giờ cầm token MISA.

Xác thực: header ``X-API-Key`` khớp System Parameter ``misa.product_api.key``. Key RIÊNG,
không dùng chung ``misa.api.token`` của các route đọc/đồng bộ: đây là quyền GHI hàng hóa
lên MISA. Chưa cấu hình key thì mọi request đều bị từ chối.

Body và kết quả là JSON thường (không bọc JSON-RPC). Kết quả luôn có ``ok``; lỗi có
thêm ``error`` (mã máy đọc) và ``message`` (người đọc):

    POST /api/misa/product/create   tạo hàng thường
    POST /api/misa/product/update   sửa tên / mã / mô tả một hàng đã có
    POST /api/misa/combo/create     tạo combo từ các mã con đã có trên MISA
    POST /api/misa/combo/update     sửa thành phần / tên / giá của combo đã có

Mã HTTP: 200 xong · 400 thiếu/sai dữ liệu · 401 thiếu key · 403 sai key · 404 không thấy
hàng cần sửa · 409 trùng (mã đã có) · 502 MISA từ chối/lỗi · 503 Odoo chưa cấu hình key.
"""
import logging

from odoo import http
from odoo.http import request

from ..utils.api_key import api_key_matches

_logger = logging.getLogger(__name__)

KEY_PARAM = 'misa.product_api.key'
UPDATABLE_FIELDS = {'name': 'name', 'code': 'code', 'description': 'Description'}


class ApiError(Exception):
    """Lỗi trả thẳng cho bên gọi, kèm mã HTTP."""

    def __init__(self, status, error, message, **extra):
        super().__init__(message)
        self.status = status
        self.error = error
        self.message = message
        self.extra = extra


def _reply(payload, status=200):
    return request.make_json_response(payload, status=status)


def _require_key():
    """Raise ApiError nếu key thiếu / sai / Odoo chưa cấu hình. Không bao giờ ghi key ra log."""
    expected = request.env['ir.config_parameter'].sudo().get_param(KEY_PARAM)
    if not (expected or '').strip():
        _logger.error("MISA_PRODUCT_API bị gọi khi chưa cấu hình %s", KEY_PARAM)
        raise ApiError(503, 'not_configured', "Odoo chưa cấu hình API key cho route này.")
    provided = request.httprequest.headers.get('X-API-Key')
    if not provided:
        raise ApiError(401, 'missing_key', "Thiếu header X-API-Key.")
    if not api_key_matches(provided, expected):
        _logger.warning("MISA_PRODUCT_API sai key từ %s", request.httprequest.remote_addr)
        raise ApiError(403, 'invalid_key', "API key không hợp lệ.")


def _body():
    try:
        data = request.get_json_data()
    except ValueError:
        raise ApiError(400, 'invalid_json', "Body phải là JSON hợp lệ.")
    if not isinstance(data, dict):
        raise ApiError(400, 'invalid_json', "Body phải là một object JSON.")
    return data


def _text(data, key, required=True):
    value = data.get(key)
    value = value.strip() if isinstance(value, str) else ''
    if required and not value:
        raise ApiError(400, 'missing_field', "Thiếu trường '%s'." % key)
    return value


def _number(data, key, default=None):
    """Số trong body. default None = bắt buộc; trường tuỳ chọn gửi null thì dùng default."""
    value = data.get(key)
    if value is None:
        if default is None:
            raise ApiError(400, 'missing_field', "Thiếu trường '%s'." % key)
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ApiError(400, 'invalid_field', "Trường '%s' phải là số." % key)


def _handle(action, work):
    """Khung chung: kiểm key TRƯỚC mọi việc, đọc body, chạy, đổi lỗi thành JSON."""
    try:
        _require_key()
        payload = work(_body(), request.env['misa.api.utils'].sudo())
        return _reply(dict(payload, ok=True))
    except ApiError as error:
        return _reply(dict(error.extra, ok=False, error=error.error, message=error.message),
                      status=error.status)
    except Exception as error:
        _logger.exception("MISA_PRODUCT_API %s lỗi", action)
        return _reply({'ok': False, 'error': 'misa_error', 'message': str(error)}, status=502)


class MisaProductApi(http.Controller):

    @http.route('/api/misa/product/create', type='http', auth='public', methods=['POST'], csrf=False)
    def create_product(self, **kw):
        """Tạo hàng thường.

        Body: ``code``, ``name``, ``tax`` (%), và ``category_id`` HOẶC ``category`` (tên
        nhóm); tuỳ chọn ``unit`` (mặc định "Cái"), ``price``, ``price_pu``, ``description``.
        Trả: ``{"ok": true, "misa_id": "...", "code": "..."}``. Mã đã có -> 409.
        """
        return _handle('create_product', _create_product)

    @http.route('/api/misa/product/update', type='http', auth='public', methods=['POST'], csrf=False)
    def update_product(self, **kw):
        """Sửa MỘT trường của hàng đã có.

        Body: ``field`` (name | code | description), ``new_value``, và cách chỉ hàng:
        ``code`` (Odoo tự tra MISA ID và giá trị cũ) HOẶC ``misa_id`` + ``old_value``.
        Trả: ``{"ok": true, "misa_id": "...", "field": "..."}``.
        """
        return _handle('update_product', _update_product)

    @http.route('/api/misa/combo/create', type='http', auth='public', methods=['POST'], csrf=False)
    def create_combo(self, **kw):
        """Tạo combo từ các mã con đã có trên MISA.

        Body: ``code``, ``name``, ``components`` = ``[{"code": "...", "quantity": 2}, ...]``;
        tuỳ chọn ``category_id``, ``unit`` (mặc định "Bộ"), ``tax`` (mặc định 8),
        ``price``, ``price_pu``, ``description``. Mã đã có -> 409.
        """
        return _handle('create_combo', _create_combo)


    @http.route('/api/misa/combo/update', type='http', auth='public', methods=['POST'], csrf=False)
    def update_combo(self, **kw):
        """Sửa combo đã có.

        Body: ``code`` (mã combo); tuỳ chọn ``components`` = danh sách thành phần MỚI ĐẦY
        ĐỦ (hàng nào không có là bị xoá khỏi combo), ``name``, ``price``, ``price_pu``.
        Trả: ``{"ok": true, "misa_id", "changed", "changes": {added, removed, changed}}``.
        """
        return _handle('update_combo', _update_combo)


# =============================================================================
# Việc thật của từng route — tách khỏi class để mỗi hàm chỉ lo dữ liệu nghiệp vụ.
# =============================================================================
def _reject_existing(misa, code):
    """Khoá chung rồi kiểm mã đã có chưa. Raise 409 nếu có."""
    misa.lock_product_creation()
    existing = misa._find_exact_crm_product_by_code(code)
    if existing:
        raise ApiError(409, 'duplicate', "Mã %s đã có trên MISA." % code,
                       misa_id=str(existing.get('misa_id') or ''), is_combo=existing.get('is_combo'))


def _create_product(data, misa):
    code = _text(data, 'code')
    name = _text(data, 'name')
    tax = _number(data, 'tax')
    category_id = data.get('category_id')
    category_name = _text(data, 'category', required=False)
    if not category_id and not category_name:
        raise ApiError(400, 'missing_field', "Cần 'category_id' hoặc 'category' (tên nhóm).")
    if not category_id:
        category_id = misa._get_category_id_by_name(misa._get_cached_crm_headers(), category_name)
        if not category_id:
            raise ApiError(400, 'unknown_category', "Không có nhóm hàng '%s' trên MISA." % category_name)

    _reject_existing(misa, code)
    misa_id = misa.create_product_misa_raw(
        code=code, name=name,
        price=_number(data, 'price', 0), price_pu=_number(data, 'price_pu', 0),
        tax_percent=tax, unit_name=_text(data, 'unit', required=False) or 'Cái',
        category_name=category_name or 'Hàng hóa', cat_id=category_id,
        description=_text(data, 'description', required=False),
    )
    _logger.info("MISA_PRODUCT_API tạo %s - %s (MISA ID %s) từ %s",
                 code, name, misa_id, request.httprequest.remote_addr)
    return {'misa_id': str(misa_id), 'code': code}


def _update_product(data, misa):
    field = _text(data, 'field')
    if field not in UPDATABLE_FIELDS:
        raise ApiError(400, 'invalid_field', "'field' chỉ nhận: %s." % ", ".join(UPDATABLE_FIELDS))
    new_value = _text(data, 'new_value')
    code = _text(data, 'code', required=False)
    misa_id = str(data.get('misa_id') or '').strip()
    old_value = data.get('old_value')

    if code:
        current = misa._find_exact_crm_product_by_code(code)
        if not current:
            raise ApiError(404, 'not_found', "Không có mã %s trên MISA." % code)
        misa_id = str(current.get('misa_id'))
        if old_value is None:
            old_value = {'name': current.get('name'), 'code': current.get('code')}.get(field, '')
    elif not misa_id or old_value is None:
        raise ApiError(400, 'missing_field', "Cần 'code', hoặc 'misa_id' kèm 'old_value'.")

    if field == 'code':
        # Đổi sang mã đã có là MISA có hai hàng cùng mã — chặn trước, cùng khoá với lệnh tạo.
        misa.lock_product_creation()
        taken = misa._find_exact_crm_product_by_code(new_value)
        if taken and str(taken.get('misa_id')) != misa_id:
            raise ApiError(409, 'duplicate', "Mã %s đã thuộc hàng khác trên MISA." % new_value,
                           misa_id=str(taken.get('misa_id') or ''))

    if not misa.update_product_field_misa(misa_id, UPDATABLE_FIELDS[field], new_value, old_value or ''):
        raise ApiError(502, 'misa_error', "MISA không nhận cập nhật %s cho MISA ID %s." % (field, misa_id))
    _logger.info("MISA_PRODUCT_API sửa MISA ID %s: %s '%s' -> '%s' từ %s",
                 misa_id, field, old_value, new_value, request.httprequest.remote_addr)
    return {'misa_id': misa_id, 'field': field}


def _components(data):
    """Danh sách mã con trong body, đã kiểm. Raise 400 nếu thiếu / sai."""
    components = data.get('components')
    if not isinstance(components, list) or not components:
        raise ApiError(400, 'missing_field', "Thiếu 'components' (danh sách mã con).")
    cleaned = []
    for item in components:
        if not isinstance(item, dict):
            raise ApiError(400, 'invalid_field', "Mỗi phần tử 'components' phải là object.")
        child_code = _text(item, 'code')
        quantity = _number(item, 'quantity')
        if quantity <= 0:
            raise ApiError(400, 'invalid_field', "Số lượng của mã con %s phải > 0." % child_code)
        cleaned.append({'code': child_code, 'quantity': quantity})
    return cleaned


def _create_combo(data, misa):
    code = _text(data, 'code')
    name = _text(data, 'name')
    cleaned = _components(data)

    _reject_existing(misa, code)
    result = misa.create_combo_product_misa_raw(
        code=code, name=name, components=cleaned,
        category_id=data.get('category_id') or None,
        unit_name=_text(data, 'unit', required=False) or 'Bộ',
        tax_percent=_number(data, 'tax', 8),
        price=_number(data, 'price', 0), price_pu=_number(data, 'price_pu', 0),
        description=_text(data, 'description', required=False) or None,
    )
    _logger.info("MISA_PRODUCT_API tạo combo %s - %s (MISA ID %s, %s mã con) từ %s",
                 code, name, result.get('id'), len(cleaned), request.httprequest.remote_addr)
    return {'misa_id': str(result.get('id')), 'code': code}


def _update_combo(data, misa):
    code = _text(data, 'code')
    components = _components(data) if data.get('components') is not None else None
    price = data.get('price')
    price_pu = data.get('price_pu')
    if components is None and not data.get('name') and price is None and price_pu is None:
        raise ApiError(400, 'missing_field', "Không có gì để sửa: cần 'components', 'name', 'price' hoặc 'price_pu'.")
    found = misa._find_exact_crm_product_by_code(code)
    if not found:
        raise ApiError(404, 'not_found', "Không có mã %s trên MISA." % code)
    if not found.get('is_combo'):
        raise ApiError(400, 'not_combo', "Mã %s không phải combo." % code)
    result = misa.update_combo_product_misa(
        code,
        components=components,
        name=_text(data, 'name', required=False) or None,
        price=None if price is None else _number(data, 'price'),
        price_pu=None if price_pu is None else _number(data, 'price_pu'),
    )
    _logger.info("MISA_PRODUCT_API sửa combo %s (MISA ID %s): %s %s từ %s", code, result.get('id'),
                 result.get('changes'), result.get('header'), request.httprequest.remote_addr)
    return {'misa_id': str(result.get('id')), 'code': code, 'changed': result.get('changed'),
            'changes': result.get('changes'), 'header': result.get('header')}
