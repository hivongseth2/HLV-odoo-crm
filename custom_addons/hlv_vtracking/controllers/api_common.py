"""Hạ tầng HTTP dùng chung cho mọi API của module.

Mọi endpoint trả về cùng một khung:
    {"success": true,  "data": {...}}
    {"success": false, "error": {"code": "...", "message": "..."}}

Xác thực bằng header ``X-API-Key`` — không dùng session Odoo, vì bên gọi là ứng dụng khác
máy (hoặc một AI agent), không có cookie.
"""

import functools
import json
import logging
from datetime import date, datetime

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import Response, request

_logger = logging.getLogger(__name__)

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, X-API-Key',
    'Access-Control-Max-Age': '86400',
}

# Tham số route giống nhau ở mọi endpoint; gom lại để không gõ sai một chỗ.
ROUTE_DEFAULTS = {'type': 'http', 'auth': 'public', 'csrf': False, 'save_session': False}


class ApiError(Exception):
    """Lỗi có chủ đích của API: mang theo mã lỗi và HTTP status để trả thẳng cho bên gọi."""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def json_response(payload, status=200):
    return Response(
        json.dumps(payload, default=str, ensure_ascii=False),
        status=status, content_type='application/json; charset=utf-8',
        headers=dict(CORS_HEADERS),
    )


def error_response(code, message, status):
    return json_response({'success': False, 'error': {'code': code, 'message': message}}, status)


def api_endpoint(write=False):
    """Decorator bọc một endpoint: preflight, xác thực, đổi lỗi thành JSON.

    Hàm được bọc nhận ``(self, ctx, ...)`` với ``ctx`` là ``ApiContext``, và chỉ cần TRẢ
    VỀ dict dữ liệu hoặc ném lỗi — không tự dựng Response.

    ``write=True`` đòi khoá API có bật "Cho phép ghi". Khoá cấp cho ứng dụng chỉ xem bản
    đồ không được phép, chỉ vì có khoá, mà sửa luôn kế hoạch giao hàng.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            if request.httprequest.method == 'OPTIONS':
                return Response(status=200, headers=dict(CORS_HEADERS))
            # Chặn ?ctx=... trên URL chui vào làm tham số thứ hai của hàm được bọc.
            kwargs.pop('ctx', None)
            try:
                ctx = ApiContext.from_request(require_write=write)
                return json_response({'success': True, 'data': func(self, ctx, *args, **kwargs)})
            except ApiError as exc:
                return error_response(exc.code, str(exc), exc.status)
            except (UserError, ValidationError) as exc:
                # Luật nghiệp vụ từ chối (xe đã có kế hoạch, kế hoạch đã khoá...). 422 để
                # bên gọi phân biệt với lỗi cú pháp request (400).
                request.env.cr.rollback()
                return error_response('BUSINESS_RULE', str(exc.args[0] if exc.args else exc), 422)
            except AccessError as exc:
                request.env.cr.rollback()
                return error_response('FORBIDDEN', str(exc), 403)
            except Exception:  # noqa: BLE001 — lỗi lạ không được lộ traceback ra ngoài
                request.env.cr.rollback()
                _logger.exception('V-Tracking API: lỗi không lường trước tại %s', request.httprequest.path)
                return error_response('SERVER_ERROR', 'Lỗi máy chủ. Xem log Odoo để biết chi tiết.', 500)
        return wrapper
    return decorator


class ApiContext:
    """Những gì một endpoint cần biết về lời gọi hiện tại: khoá, công ty, env, tham số."""

    def __init__(self, api_key, env):
        self.api_key = api_key
        self.company = api_key.company_id
        self.env = env

    @classmethod
    def from_request(cls, require_write=False):
        raw_key = request.httprequest.headers.get('X-API-Key') or ''
        api_key = request.env['hlv.vtracking.api.key'].sudo().authenticate(raw_key)
        if not api_key:
            # Không nói khoá sai hay khoá đã thu hồi: chênh lệch đó giúp người dò khoá.
            raise ApiError('UNAUTHORIZED', 'Khoá API không hợp lệ.', 401)
        if require_write and not api_key.allow_write:
            raise ApiError(
                'WRITE_NOT_ALLOWED',
                'Khoá API này chỉ được đọc. Bật "Cho phép ghi" trên khoá ở V-Tracking > '
                'Cấu hình > Khoá API.', 403,
            )
        api_key.mark_used(request.httprequest.remote_addr)
        # Môi trường quyền cao nhưng KHOÁ vào đúng công ty của khoá API: mọi search/create
        # phía sau tự nằm trong công ty đó mà không phải nhớ thêm domain ở từng chỗ.
        env = request.env(su=True, context=dict(
            request.env.context, allowed_company_ids=[api_key.company_id.id],
        ))
        return cls(api_key, env)

    # ------------------------------------------------------------------
    # Đọc tham số
    # ------------------------------------------------------------------
    def json_body(self):
        """Thân request dạng JSON object. Thân rỗng trả về dict rỗng."""
        raw = request.httprequest.get_data(as_text=True) or ''
        if not raw.strip():
            return {}
        try:
            body = json.loads(raw)
        except ValueError as exc:
            raise ApiError('BAD_JSON', 'Thân request không phải JSON hợp lệ: %s' % exc) from exc
        if not isinstance(body, dict):
            raise ApiError('BAD_JSON', 'Thân request phải là một JSON object.')
        return body

    @staticmethod
    def parse_date(value, default_today=True):
        """Chuỗi YYYY-MM-DD -> date. Rỗng trả hôm nay (hoặc None nếu ``default_today=False``)."""
        if not value:
            return date.today() if default_today else None
        try:
            return datetime.strptime(str(value), '%Y-%m-%d').date()
        except ValueError as exc:
            raise ApiError('BAD_DATE', 'Ngày phải có dạng YYYY-MM-DD, nhận được "%s".' % value) from exc

    @staticmethod
    def parse_int(value, name, default=None, minimum=None, maximum=None):
        """Chuỗi -> int trong khoảng cho phép. Rỗng trả ``default``."""
        if value in (None, ''):
            return default
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ApiError('BAD_PARAM', 'Tham số "%s" phải là số nguyên.' % name) from exc
        if minimum is not None:
            number = max(number, minimum)
        if maximum is not None:
            number = min(number, maximum)
        return number

    @staticmethod
    def parse_id_list(value, name):
        """List id từ JSON -> list int đã khử trùng, giữ thứ tự. None/rỗng trả list rỗng."""
        if not value:
            return []
        if not isinstance(value, list):
            raise ApiError('BAD_PARAM', '"%s" phải là một mảng id.' % name)
        try:
            return list(dict.fromkeys(int(item) for item in value))
        except (TypeError, ValueError) as exc:
            raise ApiError('BAD_PARAM', '"%s" chỉ được chứa số nguyên.' % name) from exc

    def browse_or_404(self, model, record_id, label):
        """Bản ghi theo id trong phạm vi công ty của khoá; ném 404 nếu không có."""
        record = self.env[model].browse(int(record_id)).exists()
        company = record.company_id if record and 'company_id' in record._fields else False
        if not record or (company and company != self.company):
            raise ApiError('NOT_FOUND', 'Không tìm thấy %s có id %s.' % (label, record_id), 404)
        return record
