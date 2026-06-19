# -*- coding: utf-8 -*-
import json
import logging

from odoo import http
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


class MisaCrmPurchaseRequestImportController(http.Controller):
    ROUTE = "/misa/crm/purchase-request/import"

    @http.route(
        ROUTE,
        type="http",
        auth="none",
        methods=["OPTIONS"],
        csrf=False,
        save_session=False,
        cors="*",
    )
    def options_purchase_request_import(self, **kwargs):
        return Response("", status=204, headers=self._cors_headers())

    @http.route(
        ROUTE,
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
        cors="*",
    )
    def import_purchase_request(self, **kwargs):
        env = request.env(user=request.env.ref("base.user_root").id)

        try:
            raw_body = request.httprequest.get_data(as_text=True) or "{}"
            payload = json.loads(raw_body)
        except Exception as exc:
            _logger.warning("Invalid CRM purchase request import payload: %s", exc)
            return self._json_response(
                {"success": False, "error": "invalid_json"},
                status=400,
            )

        token_ok, token_msg = self._verify_token(env, payload)
        if not token_ok:
            return self._json_response(
                {"success": False, "error": "unauthorized", "message": token_msg},
                status=401,
            )

        try:
            result = env["misa.crm.purchase.request.importer"].sudo().import_payload(payload)
        except Exception as exc:
            _logger.exception("CRM purchase request import failed: %s", exc)
            return self._json_response(
                {"success": False, "error": "import_failed", "message": str(exc)},
                status=400,
            )

        return self._json_response({"success": True, **result})

    def _verify_token(self, env, payload):
        configured = (
            env["ir.config_parameter"]
            .sudo()
            .get_param("misa_crm_purchase_request_bridge.api_token", "")
            .strip()
        )
        if not configured:
            return (
                False,
                "Missing Odoo config parameter misa_crm_purchase_request_bridge.api_token",
            )

        received = (
            request.httprequest.headers.get("X-Odoo-PR-Token")
            or request.httprequest.args.get("token")
            or payload.get("token")
            or ""
        ).strip()
        if received != configured:
            return False, "Invalid import token"
        return True, "OK"

    @staticmethod
    def _cors_headers():
        return [
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Headers", "Content-Type, X-Odoo-PR-Token"),
            ("Access-Control-Allow-Methods", "POST, OPTIONS"),
        ]

    def _json_response(self, body, status=200):
        return Response(
            json.dumps(body, ensure_ascii=False),
            status=status,
            mimetype="application/json",
            headers=self._cors_headers(),
        )
