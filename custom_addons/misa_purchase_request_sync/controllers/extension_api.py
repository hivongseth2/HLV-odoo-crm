# -*- coding: utf-8 -*-
# Copyright 2026 HLV
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

"""
RESTful API cho MISA CRM Browser Extension (Chrome MV3).

Endpoints:
    GET  /api/extension/pr/check?name=<name>
        -> {"ok": True, "exists": True/False, "status": "draft", "status_label": "Mới"}

    POST /api/extension/pr/create
        Body JSON:
        {
            "token": "...",
            "PurchaseRequestName": "PR00001",
            "OwnerIDText": "MAI VĂN NAM (MAIVANNAM1)",
            "lines": [
                {"product_code": "SP001", "name": "...", "qty": 10, "uom": "Cái"},
                ...
            ],
            "description": "..."
        }
        -> {"ok": True, "id": 123, "name": "PR00001"}

Xác thực: Header `X-MISA-Token: <token>` (hoặc token trong body JSON).
Token so sánh với System Parameter `misa_extension_token` (sudo).
"""

import json
import logging
import re

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


def _clean_token(token):
    """Loại bỏ zero-width chars để tránh lỗi so sánh."""
    if not token:
        return ""
    return re.sub(r"[​-‍﻿]", "", str(token)).strip()


class MisaExtensionController(http.Controller):
    """Public API endpoints cho MISA CRM Browser Extension."""

    # ============================================================
    # AUTH HELPER
    # ============================================================
    def _authenticate(self, token):
        """
        So sánh token với System Parameter `misa_extension_token`.

        :return: (ok: bool, error_response: dict | None)
        """
        expected = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("misa_extension_token", default="")
        )
        expected = _clean_token(expected)

        if not expected:
            _logger.error(
                "misa_extension_token chưa được cấu hình trong System Parameters."
            )
            return (
                False,
                {
                    "ok": False,
                    "error": "server_misconfigured",
                    "message": "Server chưa cấu hình token xác thực.",
                },
            )

        if _clean_token(token) != expected:
            return (
                False,
                {"ok": False, "error": "invalid_token", "message": "Token không hợp lệ."},
            )
        return (True, None)

    def _parse_json_body(self, payload):
        """
        Với type='json' Odoo parse sẵn vào **payload. Nếu rỗng (Postman sai
        Content-Type), tự đọc raw body.
        """
        if payload:
            return dict(payload)
        try:
            body = request.httprequest.get_json(force=False, silent=True)
        except Exception:
            body = None
        if body is None:
            raw = (request.httprequest.data or b"").decode("utf-8", errors="ignore")
            try:
                body = json.loads(raw) if raw else {}
            except Exception:
                body = {}
        return dict(body or {})

    def _extract_token(self, payload):
        """Lấy token từ body hoặc header X-MISA-Token."""
        raw = payload.get("token") or request.httprequest.headers.get("X-MISA-Token")
        return _clean_token(raw)

    # ============================================================
    # GET /api/extension/pr/check?name=PR00001
    # ============================================================
    @http.route(
        "/api/extension/pr/check",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        cors="*",
    )
    def api_extension_pr_check(self, **kwargs):
        """
        Kiểm tra YCMH đã tồn tại trên Odoo hay chưa.

        Query: ?name=PR00001
        Header: X-MISA-Token: <token>

        Response 200 JSON:
            {
                "ok": True,
                "exists": True,
                "id": 5,
                "name": "PR00001",
                "status": "draft",
                "status_label": "Mới"
            }
        """
        # ---- Auth (token có thể nằm ở query string cho GET) ----
        token = _clean_token(kwargs.get("token")) or _clean_token(
            request.httprequest.headers.get("X-MISA-Token")
        )
        ok, err = self._authenticate(token)
        if not ok:
            return request.make_response(
                json.dumps(err), headers=[("Content-Type", "application/json")]
            )

        # ---- Business logic ----
        name = (kwargs.get("name") or "").strip()
        if not name:
            return request.make_response(
                json.dumps(
                    {
                        "ok": False,
                        "error": "missing_name",
                        "message": "Thiếu tham số 'name' trên query string.",
                    }
                ),
                headers=[("Content-Type", "application/json")],
            )

        # Dùng admin env để tránh lỗi phân quyền
        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        env = request.env(user=admin_user) if admin_user else request.env
        pr = env["purchase.request"].sudo().search([("name", "=", name)], limit=1)

        if not pr:
            payload = {"ok": True, "exists": False, "name": name}
        else:
            state_label = (
                dict(pr._fields["state"].selection).get(pr.state, pr.state)
                if pr.state
                else ""
            )
            payload = {
                "ok": True,
                "exists": True,
                "id": pr.id,
                "name": pr.name,
                "status": pr.state,
                "status_label": state_label,
            }

        return request.make_response(
            json.dumps(payload), headers=[("Content-Type", "application/json")]
        )

    # ============================================================
    # POST /api/extension/pr/create
    # ============================================================
    @http.route(
        "/api/extension/pr/create",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def api_extension_pr_create(self, **payload):
        """
        Tạo YCMH mới từ payload JSON của MISA CRM.

        Body JSON:
        {
            "token": "...",                        # hoặc header X-MISA-Token
            "PurchaseRequestName": "PR00001",     # mã YCMH từ CRM
            "OwnerIDText": "MAI VĂN NAM (MAIVANNAM1)",
            "description": "YCMH từ CRM MISA",
            "lines": [
                {
                    "product_code": "SP001",      # default_code; optional
                    "name": "Sản phẩm A",
                    "qty": 10.0,
                    "uom": "Cái"                 # optional, mặc định = product.uom_id
                }
            ]
        }
        """
        # ---- Helper: Trả về HTTP Response ----
        def json_response(payload, status=200):
            return request.make_response(
                json.dumps(payload), headers=[("Content-Type", "application/json")]
            )

        payload = self._parse_json_body(payload)

        # ---- Auth ----
        token = self._extract_token(payload)
        ok, err = self._authenticate(token)
        if not ok:
            return json_response(err, 401)

        # ---- Validate ----
        pr_name = (payload.get("PurchaseRequestName") or "").strip()
        if not pr_name:
            return json_response({
                "ok": False,
                "error": "missing_purchase_request_name",
                "message": "Thiếu trường 'PurchaseRequestName'.",
            }, 400)

        lines_in = payload.get("lines") or []
        if not isinstance(lines_in, list) or not lines_in:
            return json_response({
                "ok": False,
                "error": "missing_lines",
                "message": "Thiếu danh sách 'lines' (ít nhất 1 dòng sản phẩm).",
            }, 400)

        # ---- Switch sang admin env (an toàn phân quyền) ----
        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        if not admin_user:
            return json_response({"ok": False, "error": "admin_not_found", "message": "Không tìm thấy user admin để sudo."}, 500)
        env_admin = request.env(user=admin_user)

        try:
            # --- Resolve user từ OwnerIDText ---
            pr_model = env_admin["purchase.request"]
            user_id, owner_message = pr_model._prepare_misa_user(
                payload.get("OwnerIDText")
            )

            # --- Tạo PR ---
            pr_vals = {
                "name": pr_name,
                "requested_by": user_id,
                "origin": "MISA CRM",
                "description": payload.get("description") or "",
            }
            pr = pr_model.create(pr_vals)

            # --- Tạo lines ---
            line_model = env_admin["purchase.request.line"]
            product_model = env_admin["product.product"]
            uom_model = env_admin["uom.uom"]

            for idx, line in enumerate(lines_in, start=1):
                if not isinstance(line, dict):
                    continue

                product = False
                pcode = (line.get("product_code") or "").strip()
                if pcode:
                    product = product_model.search(
                        [("default_code", "=ilike", pcode)], limit=1
                    )
                if not product:
                    # Fallback: tìm theo tên
                    pname = (line.get("name") or "").strip()
                    if pname:
                        product = product_model.search(
                            [("name", "=ilike", pname)], limit=1
                        )

                uom = False
                uom_name = (line.get("uom") or "").strip()
                if uom_name:
                    uom = uom_model.search([("name", "=ilike", uom_name)], limit=1)
                if not uom and product:
                    uom = product.uom_id

                line_vals = {
                    "request_id": pr.id,
                    "name": line.get("name") or (product.display_name if product else ""),
                    "product_id": product.id if product else False,
                    "product_qty": float(line.get("qty") or 0.0),
                    "product_uom_id": uom.id if uom else False,
                }
                line_model.create(line_vals)

            # --- Post Chatter nếu là Admin fallback ---
            if owner_message:
                pr.message_post(body=owner_message)

            return json_response({
                "ok": True,
                "id": pr.id,
                "name": pr.name,
                "state": pr.state,
                "lines_created": len(pr.line_ids),
                "owner_warning": owner_message or None,
            })

        except Exception as e:
            _logger.exception("Extension API /pr/create exception: %s", e)
            return json_response({"ok": False, "error": "exception", "message": str(e)}, 500)
