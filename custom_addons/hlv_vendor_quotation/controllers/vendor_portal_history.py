# -*- coding: utf-8 -*-
"""Tab "Lịch sử báo giá" trên link của NCC: mọi mặt hàng NCC đã báo — tìm, lọc theo ngày / sale / mặt hàng,
phân trang; kèm chỉ số tổng (tỉ lệ báo giá thành công, số đơn mua) và thống kê theo mặt hàng (tần suất
được hỏi, lượt đơn mua). Kế thừa VendorQuotePortal để dùng chung đăng nhập, khung trang."""

from urllib.parse import urlencode

from odoo import fields, http
from odoo.http import request

from ..models.history_utils import OUTCOMES, aggregate_products
from ..models.vendor_quote_access import PORTAL_ROUTE
from ..models.vendor_quote_utils import paginate
from ..services import vendor_history as history
from .vendor_portal import VendorQuotePortal

HISTORY = "lich-su"
PER_PAGE = 30
# Bảng "Mặt hàng hay được hỏi": số mặt hàng hiện (nhiều nhất trước).
TOP_PRODUCTS = 15
SEARCH_MAX = 64


class VendorHistoryPortal(VendorQuotePortal):

    @http.route(f"{PORTAL_ROUTE}/<string:token>/{HISTORY}", type="http", auth="public", methods=["GET"])
    def portal_history(self, token, page=1, **kw):
        access = self._get_access(token)
        if not access:
            return self._not_found()
        if not self._is_logged_in(access):
            return self._render_login(access, next_url=f"{PORTAL_ROUTE}/{token}/{HISTORY}")
        filters = self._read_history_filters(kw)
        requester = self._requester_cache()
        lines, truncated = history.search_lines(request.env, history.history_domain(access, **filters))
        facts = history.line_facts(lines, access.partner_id, requester)
        pager = paginate(len(facts), page, PER_PAGE)
        product = request.env["product.product"].sudo().browse(filters["product_id"]).exists()
        return self._render("hlv_vendor_quotation.portal_history", access, {
            "active_tab": "history",
            "filters": filters,
            "filter_values": {
                "q": filters["q"],
                "date_from": filters["day_from"].isoformat() if filters["day_from"] else "",
                "date_to": filters["day_to"].isoformat() if filters["day_to"] else "",
                "sale": filters["sale_code"],
            },
            "product_label": product.display_name if product else "",
            "sale_options": history.sale_options(access, requester),
            "summary": history.summarize(facts),
            "products": aggregate_products(facts)[:TOP_PRODUCTS],
            "rows": facts[pager["offset"]:pager["offset"] + pager["limit"]],
            "outcome_labels": dict(OUTCOMES),
            "truncated": truncated,
            "stat_limit": history.STAT_LINE_LIMIT,
            "pager": pager,
            "history_url": lambda **changes: self._history_url(access, filters, **changes),
        })

    @staticmethod
    def _read_history_filters(form):
        """Bộ lọc từ URL: chữ tìm, khoảng ngày (yyyy-mm-dd — sai thì bỏ qua), mã sale, id mặt hàng."""
        def day(key):
            try:
                return fields.Date.to_date((form.get(key) or "").strip()) or None
            except ValueError:
                return None

        try:
            product_id = max(0, int(form.get("product") or 0))
        except (TypeError, ValueError):
            product_id = 0
        return {
            "q": (form.get("q") or "").strip()[:SEARCH_MAX],
            "day_from": day("date_from"),
            "day_to": day("date_to"),
            "sale_code": (form.get("sale") or "").strip()[:SEARCH_MAX],
            "product_id": product_id,
        }

    @staticmethod
    def _history_url(access, filters, **changes):
        """URL trang lịch sử giữ bộ lọc hiện tại, đổi theo changes (page, product…; None = bỏ)."""
        params = {
            "q": filters["q"],
            "date_from": filters["day_from"].isoformat() if filters["day_from"] else "",
            "date_to": filters["day_to"].isoformat() if filters["day_to"] else "",
            "sale": filters["sale_code"],
            "product": filters["product_id"] or "",
        }
        params.update(changes)
        if str(params.get("page", "")) == "1":
            params.pop("page")  # trang 1 là mặc định — URL gọn
        query = urlencode({key: value for key, value in params.items() if value not in (None, "", 0)})
        base = f"{access._portal_path()}/{HISTORY}"
        return f"{base}?{query}" if query else base

    @staticmethod
    def _requester_cache():
        """"Tên – SĐT" người hỏi theo mã sale, tra danh bạ một lần cho mỗi mã."""
        contacts = request.env["hlv.vendor.sale.contact"].sudo()
        cache = {}

        def requester(code):
            if code not in cache:
                cache[code] = contacts._requester(code) if code else ""
            return cache[code]

        return requester
