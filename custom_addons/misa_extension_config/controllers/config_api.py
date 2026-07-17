# -*- coding: utf-8 -*-
# Copyright 2026 HLV
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

"""
RESTful API GET /api/extension/config
Trả về cấu hình động cho MISA Browser Extension (Chrome MV3).

Endpoint:
    GET /api/extension/config?token=<token>
        -> {
            "ok": True,
            "config_version": 1,
            "min_extension_version": "2.0.0",
            "elements": [
                {
                    "code": "create_pr_btn",
                    "name": "Tạo YCMH Odoo",
                    "element_type": "button",
                    "page_type": "purchase_request",
                    "endpoint": "/api/extension/pr/create",
                    "http_method": "POST",
                    "handler_key": "create_pr",
                    "anchor_selector": ".listmenu, div[class*='listmenu']",
                    "anchor_strategy": "first_child",
                    "tooltip": "Tạo YCMH trên Odoo",
                    "sequence": 10,
                    "styles": {"backgroundColor": "#2b88ff"},
                    "state_config": {"create": {"label": "Tạo YCMH"}},
                    "requires_data_event": "MISA_PR_DATA",
                    "auto_trigger_event": null,
                    "enabled": true
                }
            ]
        }

Xác thực: token trên query string hoặc header X-MISA-Token.
Token so sánh với System Parameter `misa_extension_token`.
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
    return re.sub(r"[\u200b-\u200d\ufeff]", "", str(token)).strip()


class MisaExtensionConfigController(http.Controller):
    """Public API endpoint GET /api/extension/config cho MISA Browser Extension."""

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

    # ============================================================
    # GET /api/extension/config
    # ============================================================
    @http.route(
        "/api/extension/config",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        cors="*",
    )
    def api_get_config(self, **kwargs):
        """
        Trả về toàn bộ cấu hình UI element cho extension.

        Query: ?token=<token>
        Header: X-MISA-Token: <token>

        Response 200 JSON:
            {
                "ok": True,
                "config_version": 1,
                "min_extension_version": "2.0.0",
                "elements": [...]
            }
        """
        # ---- Auth ----
        token = _clean_token(kwargs.get("token")) or _clean_token(
            request.httprequest.headers.get("X-MISA-Token")
        )
        ok, err = self._authenticate(token)
        if not ok:
            return request.make_response(
                json.dumps(err), headers=[("Content-Type", "application/json")]
            )

        # ---- Lấy version config mới nhất đang active ----
        version = (
            request.env["misa.extension.config.version"]
            .sudo()
            .search([("active", "=", True)], limit=1, order="version desc")
        )

        if not version:
            payload = {
                "ok": True,
                "config_version": 0,
                "min_extension_version": "1.0.0",
                "elements": [],
                "message": "Chưa có config version nào được publish.",
            }
            return request.make_response(
                json.dumps(payload), headers=[("Content-Type", "application/json")]
            )

        # ---- Lấy danh sách element active + enabled thuộc version này ----
        elements = (
            request.env["misa.extension.element"]
            .sudo()
            .search_read(
                [
                    ("version_id", "=", version.id),
                    ("active", "=", True),
                    ("enabled", "=", True),
                ],
                [
                    "code",
                    "name",
                    "element_type",
                    "page_type",
                    "endpoint",
                    "http_method",
                    "handler_key",
                    "anchor_selector",
                    "anchor_strategy",
                    "tooltip",
                    "sequence",
                    "styles",
                    "state_config",
                    "column_config",
                    "requires_data_event",
                    "auto_trigger_event",
                ],
                order="page_type, sequence, id",
            )
        )

        # ---- Parse JSON fields từ string -> object để extension dùng ngay ----
        parsed_elements = []
        for elem in elements:
            # Parse styles JSON
            styles = {}
            if elem.get("styles"):
                try:
                    styles = json.loads(elem["styles"])
                except (json.JSONDecodeError, TypeError):
                    styles = {}
            elem["styles"] = styles

            # Parse state_config JSON
            state_config = {}
            if elem.get("state_config"):
                try:
                    state_config = json.loads(elem["state_config"])
                except (json.JSONDecodeError, TypeError):
                    state_config = {}
            elem["state_config"] = state_config

            # Parse column_config JSON
            column_config = None
            if elem.get("column_config"):
                try:
                    column_config = json.loads(elem["column_config"])
                except (json.JSONDecodeError, TypeError):
                    column_config = None
            elem["column_config"] = column_config

            # Remove the raw text fields that are now parsed
            # (giữ elem nguyên các field đã parse, Odoo search_read trả dict)
            parsed_elements.append(elem)

        # ---- Build response ----
        payload = {
            "ok": True,
            "config_version": version.version,
            "min_extension_version": version.min_extension_version,
            "published_at": version.published_at.strftime("%Y-%m-%d %H:%M:%S")
            if version.published_at
            else None,
            "elements": parsed_elements,
        }

        return request.make_response(
            json.dumps(payload), headers=[("Content-Type", "application/json")]
        )