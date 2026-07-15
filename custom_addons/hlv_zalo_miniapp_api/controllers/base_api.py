# -*- coding: utf-8 -*-
import json
import logging
import time

from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class ZaloBaseAPI:
    """Base class chứa các helper dùng chung cho tất cả Zalo API controllers."""

    ALLOWED_IMAGE_MODELS = {
        "product.product",
        "product.template",
        "pos.category",
        "zalo.miniapp.banner",
        "product.multi.image",
    }

    @staticmethod
    def _get_cors_origin():
        """Return CORS origin từ config parameter, fallback về '*'."""
        try:
            origin = request.env["ir.config_parameter"].sudo().get_param(
                "zalo_api_cors_origin", "*"
            )
            return origin
        except Exception:
            return "*"

    @staticmethod
    def _cors_headers():
        """Return CORS headers dict với origin configurable."""
        origin = ZaloBaseAPI._get_cors_origin()
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
            "Access-Control-Max-Age": "86400",
        }

    @staticmethod
    def _response_success(data=None, status=200):
        payload = {"success": True, "data": data or {}}
        headers = ZaloBaseAPI._cors_headers()
        return Response(
            json.dumps(payload, default=str),
            status=status,
            content_type="application/json",
            headers=headers,
        )

    @staticmethod
    def _response_success_cached(data=None, max_age=300, status=200):
        """Response thành công với Cache-Control header (mặc định 5 phút)."""
        payload = {"success": True, "data": data or {}}
        headers = ZaloBaseAPI._cors_headers()
        headers["Cache-Control"] = f"public, max-age={max_age}"
        return Response(
            json.dumps(payload, default=str),
            status=status,
            content_type="application/json",
            headers=headers,
        )

    @staticmethod
    def _response_error(code, message, status=400):
        payload = {
            "success": False,
            "error": {"code": code, "message": message},
        }
        headers = ZaloBaseAPI._cors_headers()
        return Response(
            json.dumps(payload, default=str),
            status=status,
            content_type="application/json",
            headers=headers,
        )

    @staticmethod
    def _parse_int(value, default=0):
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_float(value, default=0.0):
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _get_image_url(model, rec_id, field="image_128"):
        """Return a relative URL for the image."""
        if not rec_id:
            return None
        return f"/api/v1/zalo/image/{model}/{rec_id}/{field}"

    @staticmethod
    def _request_json():
        raw = request.httprequest.data or b"{}"
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            _logger.warning("Failed to parse request JSON: %s", e)
            return {}

    @staticmethod
    def _parse_limit_offset(body, default_limit=20, max_limit=100):
        """Parse và validate limit/offset từ request body.
        Trả về (limit, offset) hoặc raise ValueError nếu offset âm."""
        limit = ZaloBaseAPI._parse_int(body.get("limit"), default_limit)
        offset = ZaloBaseAPI._parse_int(body.get("offset"), 0)
        if offset < 0:
            raise ValueError("offset không được âm")
        limit = min(max(limit, 1), max_limit)
        return limit, offset

    # =========================================================================
    # Auth & Ownership Verification
    # =========================================================================

    def _auth_required(self):
        """Return partner_id từ token, hoặc Response lỗi."""
        auth_header = request.httprequest.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return self._response_error("AUTH_REQUIRED", "Thiếu token xác thực", 401)
        token = auth_header[7:]
        pid = self._verify_token(token)
        if not pid:
            return self._response_error("INVALID_TOKEN", "Token không hợp lệ hoặc đã hết hạn", 401)
        return pid

    def _auth_and_verify_owner(self, contact_id):
        """Auth + kiểm tra contact_id khớp với token owner.
        Trả về partner_id nếu hợp lệ, hoặc Response lỗi nếu không."""
        result = self._auth_required()
        if isinstance(result, Response):
            return result
        if result != contact_id:
            _logger.warning(
                "Ownership mismatch: token owner=%s, requested contact_id=%s",
                result, contact_id,
            )
            return self._response_error("FORBIDDEN", "Không có quyền truy cập", 403)
        return result

    def _verify_token(self, token):
        """Verify HMAC token. Phải được override bởi subclass có logic verify cụ thể.
        Mặc định trả về None (unauthenticated)."""
        return None

    # =========================================================================
    # Logging helper
    # =========================================================================

    def _log_request(self, method, path, partner_id=None, status=200, elapsed_ms=0):
        """Ghi log cấu trúc cho mỗi API call."""
        _logger.info(
            "ZALO_API %s %s partner=%s status=%s time=%.2fms",
            method, path, partner_id or "anonymous", status, elapsed_ms,
        )