# -*- coding: utf-8 -*-
"""API MISA CRM cho hệ thống bên ngoài — Odoo giữ tài khoản MISA, bên ngoài chỉ cầm API key.

Mọi route: POST, body JSON (route không tham số gửi body rỗng cũng được), header ``X-API-Key``.
Bật/tắt và key: app MISA CRM API → Cấu hình. Hướng dẫn từng route: app MISA CRM API → Hướng dẫn API.

Mã HTTP: 200 xong · 400 thiếu/sai dữ liệu · 401 thiếu key · 403 sai key / chưa cho ghi ·
404 không thấy khách/hàng · 502 MISA lỗi · 503 API tắt / chưa có key.
"""
from datetime import date

from odoo import http
from odoo.addons.misa_fetch_po_button.controllers.misa_product_api import ApiError, _number, _text

from ..models.api_config import PARAM_ALLOW_WRITE
from ..services.crm_payloads import page_size
from .api_common import handle, int_field

ROUTE = dict(type="http", auth="public", methods=["POST"], csrf=False, save_session=False)
MAX_LINES = 200


def _keyword(data, required=False):
    return _text(data, "keyword", required=required)


def _paging(data):
    """(page ≥ 1, limit 1..100) trong body."""
    page = max(1, int_field(data, "page", required=False, default=1))
    return page, page_size(int_field(data, "limit", required=False, default=10))


class MisaCrmApi(http.Controller):

    @http.route("/api/misa-crm/ping", **ROUTE)
    def ping(self, **kw):
        """Kiểm key + trạng thái, không gọi MISA. Trả {"ok", "write_enabled"}."""
        return handle("ping", lambda data, crm: {"write_enabled": _write_enabled(crm)})

    # ── Khách hàng ───────────────────────────────────────────────────────
    @http.route("/api/misa-crm/account/search", **ROUTE)
    def account_search(self, **kw):
        """Body: ``keyword`` (tên / MST / mã KH / SĐT / địa chỉ), ``page``, ``limit`` (≤100)."""
        return handle("account_search", lambda data, crm: crm.api_account_search(_keyword(data), *_paging(data)))

    @http.route("/api/misa-crm/account/get", **ROUTE)
    def account_get(self, **kw):
        """Body: ``id`` (ID khách trên MISA). Trả {"account": {...}}."""
        return handle("account_get", lambda data, crm: {"account": crm.api_account_get(int_field(data, "id"))})

    # ── Hàng hóa ─────────────────────────────────────────────────────────
    @http.route("/api/misa-crm/product/search", **ROUTE)
    def product_search(self, **kw):
        """Body: ``keyword`` (mã / tên), ``page``, ``limit``, ``in_stock_only`` (true = chỉ hàng còn tồn)."""
        return handle("product_search", lambda data, crm: crm.api_product_search(
            _keyword(data), *_paging(data), in_stock_only=bool(data.get("in_stock_only"))))

    @http.route("/api/misa-crm/product/prices", **ROUTE)
    def product_prices(self, **kw):
        """Body: ``product_ids`` (ID hàng MISA), tuỳ chọn ``account_id`` để lấy bảng giá / giá bán gần nhất."""
        def work(data, crm):
            ids = data.get("product_ids")
            if not isinstance(ids, list) or not ids:
                raise ApiError(400, "missing_field", "Thiếu 'product_ids' (danh sách ID hàng MISA).")
            try:
                ids = [int(pid) for pid in ids]
            except (TypeError, ValueError):
                raise ApiError(400, "invalid_field", "'product_ids' phải là danh sách số nguyên.")
            return crm.api_product_prices(int_field(data, "account_id", required=False), ids)
        return handle("product_prices", work)

    # ── Cơ hội ───────────────────────────────────────────────────────────
    @http.route("/api/misa-crm/opportunity/options", **ROUTE)
    def opportunity_options(self, **kw):
        """Danh mục giai đoạn (kèm %) và nguồn gốc — để chọn ``stage_id`` / ``lead_source_id`` khi tạo."""
        return handle("opportunity_options", lambda data, crm: crm.api_opportunity_options())

    @http.route("/api/misa-crm/opportunity/search", **ROUTE)
    def opportunity_search(self, **kw):
        """Body: ``keyword`` (số cơ hội, tên, khách…), ``limit``."""
        return handle("opportunity_search", lambda data, crm: crm.api_opportunity_search(
            _keyword(data, required=True), _paging(data)[1]))

    @http.route("/api/misa-crm/opportunity/lines", **ROUTE)
    def opportunity_lines(self, **kw):
        """Body: ``id`` (ID cơ hội). Trả hàng của cơ hội."""
        return handle("opportunity_lines", lambda data, crm: crm.api_opportunity_lines(int_field(data, "id")))

    @http.route("/api/misa-crm/opportunity/create", **ROUTE)
    def opportunity_create(self, **kw):
        """Tạo cơ hội. Body: ``account_id``, ``closing_date`` (YYYY-MM-DD), ``lines``; tuỳ chọn
        ``stage_id`` (mặc định 1), ``lead_source_id``, ``name``, ``description``. Xem README.md."""
        return handle("opportunity_create", _create_opportunity, write=True)

    # ── Báo giá / đơn hàng ───────────────────────────────────────────────
    @http.route("/api/misa-crm/quote/search", **ROUTE)
    def quote_search(self, **kw):
        """Body: ``keyword`` (số báo giá BG…, tên khách…), ``limit``."""
        return handle("quote_search", lambda data, crm: crm.api_quote_search(
            _keyword(data, required=True), _paging(data)[1]))

    @http.route("/api/misa-crm/quote/lines", **ROUTE)
    def quote_lines(self, **kw):
        """Body: ``id`` (ID báo giá). Trả hàng của báo giá."""
        return handle("quote_lines", lambda data, crm: crm.api_quote_lines(int_field(data, "id")))

    @http.route("/api/misa-crm/sale-order/search", **ROUTE)
    def sale_order_search(self, **kw):
        """Body: ``keyword`` (số đơn, tên khách…), ``limit``."""
        return handle("sale_order_search", lambda data, crm: crm.api_sale_order_search(
            _keyword(data, required=True), _paging(data)[1]))

    @http.route("/api/misa-crm/sale-order/lines", **ROUTE)
    def sale_order_lines(self, **kw):
        """Body: ``id`` (ID đơn hàng). Trả hàng của đơn."""
        return handle("sale_order_lines", lambda data, crm: crm.api_sale_order_lines(int_field(data, "id")))


# =============================================================================
def _write_enabled(crm):
    return bool(crm.env["ir.config_parameter"].sudo().get_param(PARAM_ALLOW_WRITE))


def _closing_date(data):
    value = _text(data, "closing_date")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ApiError(400, "invalid_field", "'closing_date' phải dạng YYYY-MM-DD.")
    return value


def _lines(data):
    """Dòng hàng trong body, đã kiểm kiểu. Raise ApiError 400 nếu sai."""
    lines = data.get("lines") or []
    if not isinstance(lines, list) or len(lines) > MAX_LINES:
        raise ApiError(400, "invalid_field", "'lines' phải là danh sách (tối đa %s dòng)." % MAX_LINES)
    cleaned = []
    for item in lines:
        if not isinstance(item, dict):
            raise ApiError(400, "invalid_field", "Mỗi phần tử 'lines' phải là object.")
        code = _text(item, "code")
        qty = _number(item, "qty")
        if qty <= 0:
            raise ApiError(400, "invalid_field", "Số lượng của mã %s phải > 0." % code)
        has_after, has_before = item.get("price_after_tax") is not None, item.get("price") is not None
        if has_after == has_before:
            raise ApiError(400, "invalid_field",
                           "Mã %s: gửi đúng MỘT trong 'price_after_tax' (ưu tiên) hoặc 'price'." % code)
        price_key = "price_after_tax" if has_after else "price"
        price = _number(item, price_key)
        if price < 0:
            raise ApiError(400, "invalid_field", "Giá của mã %s không được âm." % code)
        cleaned.append({"code": code, "qty": qty, price_key: price,
                        "description": _text(item, "description", required=False) or None})
    return cleaned


def _create_opportunity(data, crm):
    return crm.api_opportunity_create(
        account_id=int_field(data, "account_id"),
        closing_date=_closing_date(data),
        lines=_lines(data),
        stage_id=int_field(data, "stage_id", required=False, default=1),
        lead_source_id=int_field(data, "lead_source_id", required=False),
        name=_text(data, "name", required=False) or None,
        description=_text(data, "description", required=False) or None,
    )
