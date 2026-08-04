import hashlib
import hmac
import json
import logging
import re
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
    def _normalize_vn_phone(phone):
        if not phone:
            return ""
        digits = re.sub(r"\D", "", str(phone))
        if len(digits) == 11 and digits.startswith("84"):
            digits = "0" + digits[2:]
        elif len(digits) == 12 and digits.startswith("084"):
            digits = "0" + digits[3:]
        return digits

    @staticmethod
    def _get_secret_key():
        try:
            Param = request.env["ir.config_parameter"].sudo()
            key = Param.get_param("zalo_api_secret", "")
            if not key:
                _logger.warning("zalo_api_secret not configured! Using dev fallback. Set this param in System Parameters for production.")
                return "hlv_zalo_dev_secret_2026"
            return key
        except Exception:
            return "hlv_zalo_dev_secret_2026"

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
        """Return CORS headers dict với origin configurable.
        Tránh trùng lặp Access-Control-Allow-Origin nếu route đã có cors='*'."""
        headers = {
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
            "Access-Control-Max-Age": "86400",
        }
        has_route_cors = False
        try:
            if hasattr(request, "endpoint") and request.endpoint and hasattr(request.endpoint, "routing"):
                has_route_cors = bool(request.endpoint.routing.get("cors"))
        except Exception:
            pass

        if not has_route_cors:
            headers["Access-Control-Allow-Origin"] = ZaloBaseAPI._get_cors_origin()
        return headers

    @staticmethod
    def _response_options():
        """Response 200 OK cho HTTP OPTIONS preflight request."""
        headers = ZaloBaseAPI._cors_headers()
        return Response(status=200, headers=headers)

    def _check_options(self):
        """Trả về 200 OK Response nếu request là OPTIONS preflight."""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        return None

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
    def _get_record_timestamp(record):
        if not record or not record.exists():
            return None
        try:
            from odoo import fields
            wdate = getattr(record, "write_date", None) or getattr(record, "create_date", None)
            if wdate:
                return int(fields.Datetime.to_datetime(wdate).timestamp())
        except Exception:
            pass
        return None

    @staticmethod
    def _get_image_url(model, rec_id, field="image_128", write_date=None):
        """Return a relative URL for the image with versioning.
        Uses safe model name (dots replaced with dashes) for GET endpoint.
        Frontend can use this URL directly in <img> tags.
        Example: /api/v1/zalo/image/product-product/123/image_128?v=1722749821"""
        if not rec_id:
            return None
        safe_model = model.replace(".", "-")
        url = f"/api/v1/zalo/image/{safe_model}/{rec_id}/{field}"
        if write_date:
            try:
                from odoo import fields
                if isinstance(write_date, (int, float)):
                    ts = int(write_date)
                else:
                    ts = int(fields.Datetime.to_datetime(write_date).timestamp())
                url += f"?v={ts}"
            except Exception:
                pass
        return url


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
        token = auth_header[7:].strip()
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
        """Verify HMAC token với secret key."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            partner_id = int(parts[0])
            timestamp = int(parts[1])
            signature = parts[2]

            secret = self._get_secret_key()

            partner = request.env["res.partner"].sudo().browse(partner_id)
            if not partner.exists():
                return None

            phone = partner.phone or partner.mobile or ""
            phone = self._normalize_vn_phone(phone)

            expected_payload = f"{partner_id}:{phone}:{timestamp}"
            expected_sig = hmac.new(secret.encode(), expected_payload.encode(), hashlib.sha256).hexdigest()

            if not hmac.compare_digest(signature, expected_sig):
                return None

            # Kiểm tra hết hạn: 30 ngày
            if time.time() - timestamp > 30 * 24 * 3600:
                return None

            return partner_id
        except (ValueError, IndexError, Exception):
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