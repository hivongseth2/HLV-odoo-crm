# -*- coding: utf-8 -*-
"""
API công khai (HTTP) cho báo cáo Doanh thu theo khách hàng.

Xác thực: header `X-Revenue-Token: <token>` (hoặc query param `token`). Token so sánh với
System Parameter `hlv_customer_revenue_report.api_token` - vào Settings > Technical >
Parameters > System Parameters, tạo key trên với giá trị token tự chọn trước khi dùng API.

Endpoints:
    GET /api/revenue/customers
        ?date_from=2026-01-01&date_to=2026-01-31&search=BM&shopee_filter=all
        &order_by=amount_net&order_dir=desc&limit=50&offset=0
        -> {"ok": true, "rows": [...], "total_count": N}

    GET /api/revenue/customers/monthly?group_type=partner&group_id=123&date_from=&date_to=
        -> {"ok": true, "rows": [...]}

    GET /api/revenue/customers/detail?group_type=partner&group_id=123&date_from=...&date_to=...
        -> {"ok": true, "rows": [...]}

    GET /api/revenue/customers/export
        ?date_from=...&date_to=...&search=...&shopee_filter=...
        (thêm group_type=partner|shop&group_id=123 để xuất riêng 1 khách hàng/shop)
        -> tải trực tiếp file .xlsx

group_type: "partner" (khách hàng thật) hoặc "shop" (shop Shopee - đơn Shopee được gộp
theo shop thay vì theo contact chung chung, xem models/customer_revenue_report.py).
"""

import json
import logging

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

TOKEN_PARAM = "hlv_customer_revenue_report.api_token"


class HlvRevenueApiController(http.Controller):

    # ==================== Helpers ====================
    def _authenticate(self, token):
        expected = request.env["ir.config_parameter"].sudo().get_param(TOKEN_PARAM, default="")
        if not expected:
            _logger.error("%s chưa được cấu hình trong System Parameters.", TOKEN_PARAM)
            return False, {
                "ok": False, "error": "server_misconfigured",
                "message": 'Server chưa cấu hình System Parameter "%s".' % TOKEN_PARAM,
            }
        if not token or token != expected:
            return False, {"ok": False, "error": "invalid_token", "message": "Token không hợp lệ."}
        return True, None

    def _extract_token(self, kwargs):
        return (kwargs.get("token") or request.httprequest.headers.get("X-Revenue-Token") or "").strip()

    def _json_response(self, payload, status=200):
        return request.make_response(
            json.dumps(payload, ensure_ascii=False),
            headers=[("Content-Type", "application/json")],
            status=status,
        )

    def _report_model(self):
        return request.env["hlv.customer.revenue.report"].sudo()

    def _to_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # ==================== Endpoints ====================
    @http.route("/api/revenue/customers", type="http", auth="none", methods=["GET"], csrf=False, cors="*")
    def api_revenue_customers(self, **kwargs):
        ok, err = self._authenticate(self._extract_token(kwargs))
        if not ok:
            return self._json_response(err, 401)

        limit = self._to_int(kwargs.get("limit")) or 50
        offset = self._to_int(kwargs.get("offset")) or 0

        result = self._report_model().get_customers_summary(
            date_from=kwargs.get("date_from") or False,
            date_to=kwargs.get("date_to") or False,
            search=kwargs.get("search") or False,
            shopee_filter=kwargs.get("shopee_filter") or "all",
            order_by=kwargs.get("order_by") or "amount_net",
            order_dir=kwargs.get("order_dir") or "desc",
            limit=limit,
            offset=offset,
        )
        return self._json_response({"ok": True, "rows": result["rows"], "total_count": result["total_count"]})

    @http.route("/api/revenue/customers/monthly", type="http", auth="none", methods=["GET"], csrf=False, cors="*")
    def api_revenue_customer_monthly(self, **kwargs):
        ok, err = self._authenticate(self._extract_token(kwargs))
        if not ok:
            return self._json_response(err, 401)

        group_id = self._to_int(kwargs.get("group_id"))
        if not group_id:
            return self._json_response({"ok": False, "error": "missing_group_id", "message": "Thiếu group_id."}, 400)

        try:
            rows = self._report_model().get_group_monthly_summary(
                kwargs.get("group_type") or "partner", group_id,
                date_from=kwargs.get("date_from") or False,
                date_to=kwargs.get("date_to") or False,
            )
        except UserError as e:
            return self._json_response({"ok": False, "error": "invalid_request", "message": str(e)}, 400)
        return self._json_response({"ok": True, "rows": rows})

    @http.route("/api/revenue/customers/detail", type="http", auth="none", methods=["GET"], csrf=False, cors="*")
    def api_revenue_customer_detail(self, **kwargs):
        ok, err = self._authenticate(self._extract_token(kwargs))
        if not ok:
            return self._json_response(err, 401)

        group_id = self._to_int(kwargs.get("group_id"))
        date_from = kwargs.get("date_from")
        date_to = kwargs.get("date_to")
        if not group_id or not date_from or not date_to:
            return self._json_response({
                "ok": False, "error": "missing_params", "message": "Thiếu group_id / date_from / date_to.",
            }, 400)

        try:
            rows = self._report_model().get_group_month_detail(
                kwargs.get("group_type") or "partner", group_id, date_from, date_to,
            )
        except UserError as e:
            return self._json_response({"ok": False, "error": "invalid_request", "message": str(e)}, 400)
        return self._json_response({"ok": True, "rows": rows})

    @http.route("/api/revenue/customers/export", type="http", auth="none", methods=["GET"], csrf=False, cors="*")
    def api_revenue_customers_export(self, **kwargs):
        ok, err = self._authenticate(self._extract_token(kwargs))
        if not ok:
            return self._json_response(err, 401)

        report = self._report_model()
        group_id = self._to_int(kwargs.get("group_id"))
        try:
            if group_id:
                attachment_id = report.export_group_revenue_excel(
                    kwargs.get("group_type") or "partner", group_id,
                    date_from=kwargs.get("date_from") or False,
                    date_to=kwargs.get("date_to") or False,
                )
            else:
                attachment_id = report.export_customers_summary_excel(
                    date_from=kwargs.get("date_from") or False,
                    date_to=kwargs.get("date_to") or False,
                    search=kwargs.get("search") or False,
                    shopee_filter=kwargs.get("shopee_filter") or "all",
                )
        except UserError as e:
            return self._json_response({"ok": False, "error": "invalid_request", "message": str(e)}, 400)

        attachment = request.env["ir.attachment"].sudo().browse(attachment_id)
        return request.make_response(
            attachment.raw,
            headers=[
                ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                ("Content-Disposition", 'attachment; filename="%s"' % attachment.name),
            ],
        )
