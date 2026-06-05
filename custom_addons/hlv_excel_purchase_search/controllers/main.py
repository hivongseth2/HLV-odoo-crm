# -*- coding: utf-8 -*-

import hashlib
import hmac
import logging
import math
import re
from datetime import datetime

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class HlvExcelPurchaseSearchController(http.Controller):
    def _get_latest_file(self):
        return request.env["hlv.excel.purchase.file"].sudo().search(
            [("active", "=", True)], order="write_date desc, id desc", limit=1
        )

    def _get_keyword_tokens(self, keyword):
        keyword = re.sub(r"\s+", " ", (keyword or "").strip().lower())
        tokens = []
        for token in keyword.split(" "):
            if token and token not in tokens:
                tokens.append(token)
        return tokens[:12]

    def _get_auth_session_key(self, excel_file):
        password_hash = hashlib.sha256((excel_file.access_password or "").encode("utf-8")).hexdigest()[:16]
        return f"hlv_excel_purchase_auth_{excel_file.id}_{password_hash}"

    def _is_auth_ok(self, excel_file):
        password = (excel_file.access_password or "").strip()
        if not password:
            return False
        return bool(request.session.get(self._get_auth_session_key(excel_file)))

    def _handle_auth(self, excel_file, kwargs):
        password = (excel_file.access_password or "").strip()
        if not password:
            return {
                "ok": False,
                "error": False,
                "config_error": "Trang tra cứu đang bị khóa vì admin chưa cấu hình mật khẩu truy cập.",
            }

        if self._is_auth_ok(excel_file):
            return {"ok": True, "error": False, "config_error": False}

        if request.httprequest.method == "POST":
            input_password = (kwargs.get("access_password") or "").strip()
            if hmac.compare_digest(input_password, password):
                request.session[self._get_auth_session_key(excel_file)] = True
                return request.redirect(request.httprequest.path)
            return {"ok": False, "error": "Mật khẩu không đúng. Vui lòng thử lại.", "config_error": False}

        return {"ok": False, "error": False, "config_error": False}

    def _parse_number(self, value):
        value = re.sub(r"[^\d,.\-]", "", str(value or "").strip())
        if not value:
            return None

        if "," in value and "." in value:
            last_comma = value.rfind(",")
            last_dot = value.rfind(".")
            decimal_sep = "," if last_comma > last_dot else "."
            thousands_sep = "." if decimal_sep == "," else ","
            decimal_part = value.split(decimal_sep)[-1]
            if len(decimal_part) == 3:
                decimal_sep = None
            value = value.replace(thousands_sep, "")
            if decimal_sep:
                value = value.replace(decimal_sep, ".")
        elif "," in value:
            decimal_part = value.split(",")[-1]
            value = value.replace(",", "." if 0 < len(decimal_part) < 3 else "")
        elif "." in value:
            decimal_part = value.split(".")[-1]
            if len(decimal_part) == 3:
                value = value.replace(".", "")

        try:
            return float(value)
        except Exception:
            return None

    def _format_number(self, value, decimal_places):
        number = self._parse_number(value)
        if number is None:
            return value or ""
        decimal_places = max(0, min(int(decimal_places or 0), 6))
        return f"{number:,.{decimal_places}f}"

    def _format_date(self, value):
        value = (value or "").strip()
        if not value:
            return ""
        for date_format in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(value, date_format).strftime("%d/%m/%Y")
            except Exception:
                continue
        return value

    def _format_display_value(self, value, column):
        if column.display_format == "number":
            return self._format_number(value, column.decimal_places)
        if column.display_format == "currency":
            formatted = self._format_number(value, column.decimal_places)
            symbol = (column.currency_symbol or "").strip()
            return f"{formatted} {symbol}".strip()
        if column.display_format == "date":
            return self._format_date(value)
        return value or ""

    def _prepare_search_values(self, excel_file, keyword, page):
        keyword = (keyword or "").strip()
        page = max(page, 1)
        per_page = 50
        domain = [("file_id", "=", excel_file.id)]
        tokens = self._get_keyword_tokens(keyword)
        for token in tokens:
            domain.append(("search_text", "ilike", token))

        Line = request.env["hlv.excel.purchase.line"].sudo()
        total = Line.search_count(domain) if tokens else 0
        lines = Line.search(domain, offset=(page - 1) * per_page, limit=per_page) if tokens else Line.browse()
        columns = excel_file.column_ids.filtered("show_public").sorted("sequence")

        rows = []
        for line in lines:
            row_values = line.get_row_values()
            rows.append({
                "excel_row": line.excel_row,
                "values": [
                    self._format_display_value(row_values.get(str(column.sequence), ""), column)
                    for column in columns
                ],
            })

        pager = request.website.pager(
            url=f"/excel-purchase-search/{excel_file.public_slug}",
            total=total,
            page=page,
            step=per_page,
            scope=7,
            url_args={"q": keyword},
        )

        return {
            "not_found": False,
            "excel_file": excel_file,
            "columns": columns,
            "rows": rows,
            "keyword": keyword,
            "searched": bool(tokens),
            "total": total,
            "page": page,
            "per_page": per_page,
            "page_count": int(math.ceil(total / float(per_page))) if total else 0,
            "pager": pager,
            "error": False,
            "auth_ok": True,
            "auth_error": False,
            "auth_config_error": False,
        }

    @http.route(["/excel-purchase-search"], type="http", auth="public", website=True, sitemap=False)
    def excel_purchase_search_latest(self, **kwargs):
        excel_file = self._get_latest_file()
        if not excel_file:
            return request.render("hlv_excel_purchase_search.public_search_template", {
                "not_found": True,
                "excel_file": False,
                "keyword": "",
                "searched": False,
                "total": 0,
                "auth_ok": True,
                "auth_error": False,
                "auth_config_error": False,
            })
        return request.redirect(f"/excel-purchase-search/{excel_file.public_slug}")

    @http.route(
        ["/excel-purchase-search/<string:slug>", "/excel-purchase-search/<string:slug>/page/<int:page>"],
        type="http",
        auth="public",
        website=True,
        sitemap=False,
        methods=["GET", "POST"],
    )
    def excel_purchase_search(self, slug, page=1, **kwargs):
        excel_file = request.env["hlv.excel.purchase.file"].sudo().search(
            [("public_slug", "=", slug), ("active", "=", True)], limit=1
        )
        if not excel_file:
            return request.render("hlv_excel_purchase_search.public_search_template", {
                "not_found": True,
                "excel_file": False,
                "keyword": kwargs.get("q", ""),
                "searched": False,
                "total": 0,
                "auth_ok": True,
                "auth_error": False,
                "auth_config_error": False,
            })

        auth_result = self._handle_auth(excel_file, kwargs)
        if not isinstance(auth_result, dict):
            return auth_result
        if not auth_result["ok"]:
            return request.render("hlv_excel_purchase_search.public_search_template", {
                "not_found": False,
                "excel_file": excel_file,
                "keyword": "",
                "searched": False,
                "total": 0,
                "rows": [],
                "columns": [],
                "pager": {},
                "error": False,
                "auth_ok": False,
                "auth_error": auth_result.get("error"),
                "auth_config_error": auth_result.get("config_error"),
            })

        try:
            values = self._prepare_search_values(excel_file, kwargs.get("q", ""), page)
        except Exception as exc:
            _logger.exception("Excel purchase public search error")
            values = {
                "not_found": False,
                "excel_file": excel_file,
                "columns": excel_file.column_ids.filtered("show_public").sorted("sequence"),
                "rows": [],
                "keyword": kwargs.get("q", ""),
                "searched": bool(kwargs.get("q")),
                "total": 0,
                "pager": {},
                "error": str(exc),
                "auth_ok": True,
                "auth_error": False,
                "auth_config_error": False,
            }
        return request.render("hlv_excel_purchase_search.public_search_template", values)
