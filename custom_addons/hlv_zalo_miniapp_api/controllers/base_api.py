# -*- coding: utf-8 -*-
import json
import logging

from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class ZaloBaseAPI:
    """Base class chứa các helper dùng chung cho tất cả Zalo API controllers."""

    CORS_HEADERS = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
        "Access-Control-Max-Age": "86400",
    }

    @staticmethod
    def _cors_headers():
        """Return CORS headers dict."""
        return ZaloBaseAPI.CORS_HEADERS

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
