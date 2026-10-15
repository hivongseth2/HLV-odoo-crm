# -*- coding: utf-8 -*-
"""API MISA CRM cho hệ thống bên ngoài — Odoo giữ tài khoản MISA, bên ngoài chỉ cầm API key.

Mọi route: POST, body JSON (route không tham số gửi body rỗng cũng được), header ``X-API-Key``.
Bật/tắt và key: app MISA CRM API → Cấu hình. Hướng dẫn từng route: app MISA CRM API → Hướng dẫn API.

Mã HTTP: 200 xong · 400 thiếu/sai dữ liệu · 401 thiếu key · 403 sai key / chưa cho ghi ·
404 không thấy khách/hàng/bản ghi · 502 MISA lỗi · 503 API tắt / chưa có key.
"""
from odoo import http
from odoo.addons.misa_fetch_po_button.controllers.misa_product_api import ApiError, _text

from ..models.api_config import PARAM_ALLOW_WRITE
from . import body_fields as body
from .api_common import handle, int_field

ROUTE = dict(type="http", auth="public", methods=["POST"], csrf=False, save_session=False)


class MisaCrmApi(http.Controller):

    @http.route("/api/misa-crm/ping", **ROUTE)
    def ping(self, **kw):
        """Kiểm key + trạng thái, không gọi MISA. Trả {"ok", "write_enabled"}."""
        return handle("ping", lambda data, crm: {"write_enabled": _write_enabled(crm)})

    # ── Khách hàng ───────────────────────────────────────────────────────
    @http.route("/api/misa-crm/account/search", **ROUTE)
    def account_search(self, **kw):
        """Body: ``keyword`` (tên / MST / mã KH / SĐT / địa chỉ), ``page``, ``limit`` (≤100)."""
        return handle("account_search", lambda data, crm: crm.api_account_search(
            body.keyword(data), *body.paging(data)))

    @http.route("/api/misa-crm/account/get", **ROUTE)
    def account_get(self, **kw):
        """Body: ``id`` (ID khách trên MISA). Trả {"account": {...}}."""
        return handle("account_get", lambda data, crm: {"account": crm.api_account_get(int_field(data, "id"))})

    # ── Hàng hóa ─────────────────────────────────────────────────────────
    @http.route("/api/misa-crm/product/search", **ROUTE)
    def product_search(self, **kw):
        """Body: ``keyword`` (mã / tên), ``page``, ``limit``, ``in_stock_only`` (true = chỉ hàng còn tồn)."""
        return handle("product_search", lambda data, crm: crm.api_product_search(
            body.keyword(data), *body.paging(data), in_stock_only=bool(data.get("in_stock_only"))))

    @http.route("/api/misa-crm/product/prices", **ROUTE)
    def product_prices(self, **kw):
        """Body: ``product_ids`` (ID hàng MISA), tuỳ chọn ``account_id`` để lấy bảng giá / giá bán gần nhất."""
        return handle("product_prices", _product_prices)

    # ── Cơ hội ───────────────────────────────────────────────────────────
    @http.route("/api/misa-crm/opportunity/options", **ROUTE)
    def opportunity_options(self, **kw):
        """Danh mục giai đoạn (kèm %) và nguồn gốc — để chọn ``stage_id`` / ``lead_source_id``."""
        return handle("opportunity_options", lambda data, crm: crm.api_opportunity_options())

    @http.route("/api/misa-crm/opportunity/search", **ROUTE)
    def opportunity_search(self, **kw):
        """Body: ``keyword`` (số cơ hội, tên, khách…), ``limit``."""
        return handle("opportunity_search", lambda data, crm: crm.api_opportunity_search(
            body.keyword(data, required=True), body.paging(data)[1]))

    @http.route("/api/misa-crm/opportunity/lines", **ROUTE)
    def opportunity_lines(self, **kw):
        """Body: ``id`` (ID cơ hội). Trả hàng của cơ hội."""
        return handle("opportunity_lines", lambda data, crm: crm.api_opportunity_lines(int_field(data, "id")))

    @http.route("/api/misa-crm/opportunity/create", **ROUTE)
    def opportunity_create(self, **kw):
        """Tạo cơ hội. Xem Hướng dẫn API."""
        return handle("opportunity_create", _create_opportunity, write=True)

    @http.route("/api/misa-crm/opportunity/update", **ROUTE)
    def opportunity_update(self, **kw):
        """Sửa cơ hội: ``id`` + trường cần đổi; ``lines`` (nếu gửi) thay toàn bộ hàng."""
        return handle("opportunity_update", _update_opportunity, write=True)

    # ── Báo giá ──────────────────────────────────────────────────────────
    @http.route("/api/misa-crm/quote/options", **ROUTE)
    def quote_options(self, **kw):
        """Danh mục tình trạng báo giá — để chọn ``stage_id``."""
        return handle("quote_options", lambda data, crm: crm.api_quote_options())

    @http.route("/api/misa-crm/quote/search", **ROUTE)
    def quote_search(self, **kw):
        """Body: ``keyword`` (số báo giá BG…, tên khách…), ``limit``."""
        return handle("quote_search", lambda data, crm: crm.api_quote_search(
            body.keyword(data, required=True), body.paging(data)[1]))

    @http.route("/api/misa-crm/quote/lines", **ROUTE)
    def quote_lines(self, **kw):
        """Body: ``id`` (ID báo giá). Trả hàng của báo giá."""
        return handle("quote_lines", lambda data, crm: crm.api_quote_lines(int_field(data, "id")))

    @http.route("/api/misa-crm/quote/create", **ROUTE)
    def quote_create(self, **kw):
        """Tạo báo giá kèm hàng. Xem Hướng dẫn API."""
        return handle("quote_create", _create_quote, write=True)

    @http.route("/api/misa-crm/quote/create-from-opportunity", **ROUTE)
    def quote_create_from_opportunity(self, **kw):
        """Tạo báo giá từ cơ hội (chép khách + hàng). Xem Hướng dẫn API."""
        return handle("quote_create_from_opportunity", _create_quote_from_opportunity, write=True)

    @http.route("/api/misa-crm/quote/update", **ROUTE)
    def quote_update(self, **kw):
        """Sửa báo giá: ``id`` + trường cần đổi; ``lines`` (nếu gửi) thay toàn bộ hàng."""
        return handle("quote_update", _update_quote, write=True)

    # ── Đơn hàng ─────────────────────────────────────────────────────────
    @http.route("/api/misa-crm/sale-order/search", **ROUTE)
    def sale_order_search(self, **kw):
        """Body: ``keyword`` (số đơn, tên khách…), ``limit``."""
        return handle("sale_order_search", lambda data, crm: crm.api_sale_order_search(
            body.keyword(data, required=True), body.paging(data)[1]))

    @http.route("/api/misa-crm/sale-order/lines", **ROUTE)
    def sale_order_lines(self, **kw):
        """Body: ``id`` (ID đơn hàng). Trả hàng của đơn."""
        return handle("sale_order_lines", lambda data, crm: crm.api_sale_order_lines(int_field(data, "id")))


# =============================================================================
# Việc của từng route — tách khỏi class để mỗi hàm chỉ lo đọc body và gọi model.
# =============================================================================
def _write_enabled(crm):
    return bool(crm.env["ir.config_parameter"].sudo().get_param(PARAM_ALLOW_WRITE))


def _product_prices(data, crm):
    ids = data.get("product_ids")
    if not isinstance(ids, list) or not ids:
        raise ApiError(400, "missing_field", "Thiếu 'product_ids' (danh sách ID hàng MISA).")
    try:
        ids = [int(pid) for pid in ids]
    except (TypeError, ValueError):
        raise ApiError(400, "invalid_field", "'product_ids' phải là danh sách số nguyên.")
    return crm.api_product_prices(int_field(data, "account_id", required=False), ids)


def _create_opportunity(data, crm):
    return crm.api_opportunity_create(
        account_id=int_field(data, "account_id"),
        closing_date=body.date_field(data, "closing_date", required=True),
        lines=body.lines(data) or [],
        stage_id=int_field(data, "stage_id", required=False, default=1),
        lead_source_id=int_field(data, "lead_source_id", required=False),
        name=_text(data, "name", required=False) or None,
        description=_text(data, "description", required=False) or None,
    )


def _update_opportunity(data, crm):
    return crm.api_opportunity_update(
        int_field(data, "id"),
        name=_text(data, "name", required=False) or None,
        stage_id=int_field(data, "stage_id", required=False),
        closing_date=body.date_field(data, "closing_date"),
        lead_source_id=int_field(data, "lead_source_id", required=False),
        # Gửi "description": "" là xoá mô tả; không gửi là giữ nguyên.
        description=_text(data, "description", required=False) if body.has(data, "description") else None,
        lines=body.lines(data),
    )


def _create_quote(data, crm):
    lines = body.lines(data, allow_empty=False)
    if lines is None:
        raise ApiError(400, "missing_field", "Thiếu 'lines' — báo giá phải có ít nhất một dòng hàng.")
    return crm.api_quote_create(
        int_field(data, "account_id"), lines, body.quote_header(data, create=True),
        opportunity_id=int_field(data, "opportunity_id", required=False),
        stage_id=int_field(data, "stage_id", required=False),
    )


def _create_quote_from_opportunity(data, crm):
    return crm.api_quote_create_from_opportunity(
        int_field(data, "opportunity_id"), body.quote_header(data, create=True),
        stage_id=int_field(data, "stage_id", required=False),
    )


def _update_quote(data, crm):
    return crm.api_quote_update(
        int_field(data, "id"), body.quote_header(data, create=False),
        lines=body.lines(data, allow_empty=False),
        stage_id=int_field(data, "stage_id", required=False),
    )
