# -*- coding: utf-8 -*-

import logging
import math
import re

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
        columns = excel_file.column_ids.sorted("sequence")

        rows = []
        for line in lines:
            row_values = line.get_row_values()
            rows.append({
                "excel_row": line.excel_row,
                "values": [row_values.get(str(column.sequence), "") for column in columns],
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
        }

    @http.route(["/excel-purchase-search"], type="http", auth="public", website=True, sitemap=False)
    def excel_purchase_search_latest(self, **kwargs):
        excel_file = self._get_latest_file()
        if not excel_file:
            return request.render("hlv_excel_purchase_search.public_search_template", {
                "not_found": True,
                "excel_file": False,
                "keyword": "",
            })
        return request.redirect(f"/excel-purchase-search/{excel_file.public_slug}")

    @http.route(
        ["/excel-purchase-search/<string:slug>", "/excel-purchase-search/<string:slug>/page/<int:page>"],
        type="http",
        auth="public",
        website=True,
        sitemap=False,
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
            })

        try:
            values = self._prepare_search_values(excel_file, kwargs.get("q", ""), page)
        except Exception as exc:
            _logger.exception("Excel purchase public search error")
            values = {
                "not_found": False,
                "excel_file": excel_file,
                "columns": excel_file.column_ids.sorted("sequence"),
                "rows": [],
                "keyword": kwargs.get("q", ""),
                "searched": bool(kwargs.get("q")),
                "total": 0,
                "pager": {},
                "error": str(exc),
            }
        return request.render("hlv_excel_purchase_search.public_search_template", values)
