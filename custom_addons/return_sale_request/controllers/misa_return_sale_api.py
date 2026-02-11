# -*- coding: utf-8 -*-
"""
API endpoint để sync Return Sale Request từ MISA CRM theo mã
Tương tự misa_purchase_request_api.py
"""
import logging
import json
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MisaApiReturnSale(http.Controller):

    @http.route(
        "/api/misa/return_sale/sync",
        type="json",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def api_misa_return_sale_sync(self, **payload):
        """
        Public API: không yêu cầu login.
        Body JSON ví dụ:
        {
          "token": "hoanglongvu",
          "return_sale_code": "DNTL0000537",
          "create_when_missing": true
        }

        Trả về:
        {
          "ok": true/false,
          "res_id": 123,
          "name": "DNTH0000001",
          "action": "created" | "updated" | "not_found",
          "detail": "Chi tiết kết quả"
        }
        """
        # ---- Lấy JSON body an toàn ----
        try:
            if not payload:
                try:
                    body = request.httprequest.get_json(force=False, silent=True)
                except Exception:
                    body = None
                if body is None:
                    raw = (request.httprequest.data or b"").decode(
                        "utf-8", errors="ignore"
                    )
                    try:
                        body = json.loads(raw) if raw else {}
                    except Exception:
                        body = {}
                payload = dict(body or {})
        except Exception:
            pass

        # ---- Lấy token từ body hoặc header ----
        raw_token = (
            payload.get("token") if isinstance(payload, dict) else None
        ) or request.httprequest.headers.get("X-MISA-Token")
        token = (raw_token or "").strip()

        _logger.info(
            "MISA Return Sale API /sync payload=%r token=%r", payload, token
        )

        # ---- Token check ----
        expected = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("misa.api.token")
            or "hoanglongvu"
        )

        try:
            import re

            token = re.sub(r"[\u200B-\u200D\uFEFF]", "", token)
            expected = re.sub(r"[\u200B-\u200D\uFEFF]", "", expected)
        except Exception:
            pass

        if token != expected:
            return {
                "ok": False,
                "error": "invalid_token",
                "message": "Token không hợp lệ.",
            }

        # ---- Lấy tham số nghiệp vụ ----
        return_sale_code = payload.get("return_sale_code")
        create_when_missing = payload.get("create_when_missing", True)

        if not return_sale_code:
            return {
                "ok": False,
                "error": "missing_return_sale_code",
                "message": "Thiếu mã đề nghị trả hàng (return_sale_code)",
            }

        # ---- Chạy dưới quyền admin ----
        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        if not admin_user:
            return {"ok": False, "error": "admin_not_found"}

        try:
            env_admin = request.env(user=admin_user)

            result = env_admin["return.sale.request"].api_sync_by_code(
                return_sale_code=return_sale_code,
                create_when_missing=bool(create_when_missing),
            )
            return result
        except Exception as e:
            _logger.exception("MISA Return Sale API /sync exception: %s", e)
            return {"ok": False, "error": "exception", "message": str(e)}
