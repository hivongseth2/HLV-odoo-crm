# -*- coding: utf-8 -*-
import json
import logging
import re

from odoo import http
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


class HlvInvoiceGuardController(http.Controller):
    @http.route(
        "/api/hlv/invoice_guard/sale",
        type="http",
        auth="public",
        methods=["GET", "POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def sale_payload(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return self._json_response({})

        payload = self._request_payload(kwargs)
        token_error = self._validate_token(payload)
        if token_error:
            return self._json_response(token_error, status=401)

        sale_name = (payload.get("sale_name") or payload.get("name") or "").strip()
        if not sale_name:
            return self._json_response({"ok": False, "error": "missing_sale_name"}, status=400)

        order = self._find_sale_order(sale_name)
        if not order:
            return self._json_response({"ok": False, "error": "sale_not_found", "sale_name": sale_name}, status=404)

        return self._json_response({"ok": True, **order.hlv_invoice_guard_payload()})

    @http.route(
        "/api/hlv/invoice_guard/check",
        type="http",
        auth="public",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def check_invoice(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return self._json_response({})

        payload = self._request_payload(kwargs)
        token_error = self._validate_token(payload)
        if token_error:
            return self._json_response(token_error, status=401)

        sale_name = (payload.get("sale_name") or payload.get("name") or "").strip()
        if not sale_name:
            return self._json_response({"ok": False, "error": "missing_sale_name"}, status=400)

        order = self._find_sale_order(sale_name)
        if not order:
            return self._json_response({"ok": False, "error": "sale_not_found", "sale_name": sale_name}, status=404)

        try:
            result = order.hlv_invoice_guard_check(payload.get("lines") or [])
            return self._json_response({"ok": True, **result})
        except Exception as exc:
            _logger.exception("Invoice guard check failed for sale %s", sale_name)
            return self._json_response({"ok": False, "error": "exception", "message": str(exc)}, status=500)

    def _find_sale_order(self, sale_name):
        SaleOrder = request.env["sale.order"].sudo()
        order = SaleOrder.search([("name", "=", sale_name)], limit=1)
        if order:
            return order
        return SaleOrder.search([("client_order_ref", "=", sale_name)], limit=1)

    def _request_payload(self, kwargs):
        payload = dict(kwargs or {})
        raw = request.httprequest.get_data(cache=False, as_text=True) or ""
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    payload.update(parsed)
            except Exception:
                _logger.debug("Invoice guard received non-JSON body: %s", raw[:200])
        return payload

    def _validate_token(self, payload):
        expected = request.env["ir.config_parameter"].sudo().get_param("hlv_invoice_guard.api_token") or ""
        expected = self._clean_token(expected)
        if not expected:
            return {
                "ok": False,
                "error": "api_token_not_configured",
                "message": "Chưa cấu hình hlv_invoice_guard.api_token trong Odoo.",
            }

        token = payload.get("token") or request.httprequest.headers.get("X-HLV-Invoice-Guard-Token") or ""
        if self._clean_token(token) != expected:
            return {"ok": False, "error": "invalid_token", "message": "Token không hợp lệ."}
        return None

    def _clean_token(self, token):
        return re.sub(r"[\u200B-\u200D\uFEFF]", "", (token or "").strip())

    def _json_response(self, data, status=200):
        return Response(
            json.dumps(data, ensure_ascii=False, default=str),
            status=status,
            content_type="application/json; charset=utf-8",
            headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Content-Type, X-HLV-Invoice-Guard-Token"),
            ],
        )
