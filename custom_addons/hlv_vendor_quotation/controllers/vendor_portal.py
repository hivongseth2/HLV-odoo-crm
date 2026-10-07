# -*- coding: utf-8 -*-
"""Link công khai cho NCC: đăng nhập bằng mật khẩu, xem và điền các yêu cầu báo giá."""

import hmac
from urllib.parse import urlencode

from markupsafe import Markup
from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..models.vendor_quote import VENDOR_STATUSES, VENDOR_VISIBLE_STATES
from ..models.vendor_quote_access import LOCK_MINUTES, PORTAL_ROUTE
from ..models.vendor_quote_line import VAT_SELECTION
from ..models.vendor_quote_utils import deadline_hint, format_vn_number, paginate, parse_vn_number

SESSION_KEY = "hlv_vendor_quote_logins"
VENDOR_NOTE_MAX = 2000
LINE_NOTE_MAX = 255
PER_PAGE = 20
SEARCH_MAX = 100
IMAGE_SIZES = (128, 1024)
# (nhãn, lớp css) theo trạng thái NCC thấy; "all" chỉ là tab lọc.
STATUS_DISPLAY = {
    "all": ("Tất cả", ""),
    "waiting": ("Chờ báo giá", "waiting"),
    "quoted": ("Đã gửi giá", "quoted"),
    "expired": ("Hết hạn", "closed"),
    "closed": ("Đã đóng", "closed"),
}


class VendorQuotePortal(http.Controller):

    @http.route(f"{PORTAL_ROUTE}/<string:token>", type="http", auth="public", methods=["GET"])
    def portal_home(self, token, status="all", q="", page=1, **kw):
        access = self._get_access(token)
        if not access:
            return self._not_found()
        if not self._is_logged_in(access):
            return self._render_login(access)

        status = status if status in STATUS_DISPLAY else "all"
        q = (q or "").strip()[:SEARCH_MAX]
        Quote = request.env["hlv.vendor.quote"].sudo()
        base_domain = self._list_domain(access, q)
        counts = {"all": Quote.search_count(base_domain)}
        for key in VENDOR_STATUSES:
            counts[key] = Quote.search_count(base_domain + Quote._vendor_status_domain(key))

        domain = base_domain if status == "all" else base_domain + Quote._vendor_status_domain(status)
        pager = paginate(counts[status], page, PER_PAGE)
        quotes = Quote.search(domain, order="id desc", offset=pager["offset"], limit=pager["limit"])
        return self._render("hlv_vendor_quotation.portal_quote_list", access, {
            "quotes": quotes,
            "statuses": {quote.id: STATUS_DISPLAY[quote._vendor_status()] for quote in quotes},
            "hints": {quote.id: deadline_hint(quote.date_deadline, Quote._vendor_today()) for quote in quotes},
            # Đơn mua sinh ra từ từng báo giá — NCC thấy hỏi giá nào đã thành đơn.
            "quote_orders": {quote.id: quote._vendor_purchase_orders() for quote in quotes},
            "active_tab": "quotes",
            "tabs": [
                (key, STATUS_DISPLAY[key][0], counts[key], self._list_url(access, key, q))
                for key in ("all",) + VENDOR_STATUSES
            ],
            "status": status,
            "q": q,
            "pager": pager,
            "prev_page_url": self._list_url(access, status, q, pager["page"] - 1),
            "next_page_url": self._list_url(access, status, q, pager["page"] + 1),
        })

    @http.route(f"{PORTAL_ROUTE}/<string:token>/login", type="http", auth="public", methods=["POST"])
    def portal_login(self, token, password="", next_url="", **kw):
        access = self._get_access(token)
        if not access:
            return self._not_found()
        result = access._vendor_login(password)
        if result == "ok":
            self._remember_login(access)
            return request.redirect(self._safe_next(access, next_url))
        error = (
            f"Nhập sai quá nhiều lần. Vui lòng thử lại sau {LOCK_MINUTES} phút."
            if result == "locked"
            else "Mật khẩu không đúng."
        )
        return self._render_login(access, error=error, next_url=next_url)

    @http.route(f"{PORTAL_ROUTE}/<string:token>/logout", type="http", auth="public", methods=["GET"])
    def portal_logout(self, token, **kw):
        logins = dict(request.session.get(SESSION_KEY) or {})
        access = self._get_access(token)
        if access:
            logins.pop(str(access.id), None)
            request.session[SESSION_KEY] = logins
        return request.redirect(f"{PORTAL_ROUTE}/{token}")

    @http.route(
        f"{PORTAL_ROUTE}/<string:token>/<int:quote_id>",
        type="http",
        auth="public",
        methods=["GET", "POST"],
    )
    def portal_quote(self, token, quote_id, **post):
        access = self._get_access(token)
        if not access:
            return self._not_found()
        if not self._is_logged_in(access):
            # Link thẳng vào báo giá: đăng nhập xong quay lại đúng báo giá này.
            return self._render_login(access, next_url=f"{PORTAL_ROUTE}/{token}/{quote_id}")
        quote = self._get_quote(access, quote_id)
        if not quote:
            return self._not_found()

        values = {"quote": quote, "saved": bool(post.get("saved"))}
        if request.httprequest.method == "POST":
            line_values, errors = self._read_quote_form(quote, post)
            if not errors:
                try:
                    quote._vendor_submit(line_values, (post.get("vendor_note") or "")[:VENDOR_NOTE_MAX])
                except UserError as exc:
                    errors = [exc.args[0]]
                else:
                    return request.redirect(f"{PORTAL_ROUTE}/{token}/{quote.id}?saved=1")
            values.update(post=post, errors=errors, saved=False)
        values.update(
            status=STATUS_DISPLAY[quote._vendor_status()],
            editable=quote._is_open_for_vendor(),
            hint=deadline_hint(quote.date_deadline, quote._vendor_today()),
            contact=quote.user_id,
            company=quote.company_id or request.env.company.sudo(),
            orders=quote._vendor_purchase_orders(),
        )
        return self._render("hlv_vendor_quotation.portal_quote_form", access, values)

    @http.route(
        f"{PORTAL_ROUTE}/<string:token>/img/<int:line_id>/<int:size>",
        type="http",
        auth="public",
        methods=["GET"],
    )
    def portal_line_image(self, token, line_id, size, **kw):
        """Ảnh sản phẩm của một dòng báo giá — /web/image không mở cho khách chưa đăng nhập."""
        access = self._get_access(token)
        if not access or not self._is_logged_in(access) or size not in IMAGE_SIZES:
            return request.not_found()
        line = request.env["hlv.vendor.quote.line"].sudo().browse(line_id).exists()
        if not line or line.quote_id.access_id != access or line.quote_state not in VENDOR_VISIBLE_STATES:
            return request.not_found()
        stream = request.env["ir.binary"]._get_image_stream_from(line.product_id, f"image_{size}")
        return stream.get_response()

    # ------------------------------------------------------------------
    def _get_access(self, token):
        if not token:
            return None
        Access = request.env["hlv.vendor.quote.access"].sudo()
        return Access.search([("access_token", "=", token)], limit=1) or None

    def _get_quote(self, access, quote_id):
        return request.env["hlv.vendor.quote"].sudo().search([
            ("id", "=", quote_id),
            ("access_id", "=", access.id),
            ("state", "in", VENDOR_VISIBLE_STATES),
        ], limit=1)

    def _list_domain(self, access, q):
        domain = [("access_id", "=", access.id), ("state", "in", VENDOR_VISIBLE_STATES)]
        if q:
            domain += [
                "|", "|",
                ("name", "ilike", q),
                ("line_ids.name", "ilike", q),
                ("line_ids.product_id", "ilike", q),
            ]
        return domain

    def _list_url(self, access, status="all", q="", page=1):
        params = {"status": status if status != "all" else None, "q": q or None, "page": page if page > 1 else None}
        query = urlencode({key: value for key, value in params.items() if value})
        base = f"{PORTAL_ROUTE}/{access.access_token}"
        return f"{base}?{query}" if query else base

    def _safe_next(self, access, next_url):
        """Chỉ cho quay về trang trong chính link của NCC này — chặn open redirect."""
        base = f"{PORTAL_ROUTE}/{access.access_token}"
        next_url = next_url or ""
        if next_url == base or (
            next_url.startswith((f"{base}/", f"{base}?")) and "//" not in next_url and "\\" not in next_url
        ):
            return next_url
        return base

    def _is_logged_in(self, access):
        saved = (request.session.get(SESSION_KEY) or {}).get(str(access.id), "")
        return hmac.compare_digest(saved.encode(), access._session_key().encode())

    def _remember_login(self, access):
        # Gán lại cả dict: session của Odoo chỉ biết "đã đổi" khi gán key, không khi sửa dict lồng.
        logins = dict(request.session.get(SESSION_KEY) or {})
        logins[str(access.id)] = access._session_key()
        request.session[SESSION_KEY] = logins

    def _read_quote_form(self, quote, post):
        """Đọc ô nhập theo từng dòng. Trả (giá trị theo id dòng, danh sách lỗi đọc số)."""
        valid_vat = {key for key, _label in VAT_SELECTION}
        line_values, errors = {}, []
        for index, line in enumerate(quote.line_ids, start=1):
            raw_price = (post.get(f"price_{line.id}") or "").strip()
            price = parse_vn_number(raw_price)
            if raw_price and price is None:
                errors.append(f"Dòng {index}: không đọc được đơn giá \"{raw_price}\".")
            vat = post.get(f"vat_{line.id}") or False
            if vat and vat not in valid_vat:
                vat = False
            raw_days = (post.get(f"days_{line.id}") or "").strip()
            days = int(raw_days) if raw_days.isdigit() else 0
            if raw_days and not raw_days.isdigit():
                errors.append(f"Dòng {index}: số ngày giao \"{raw_days}\" phải là số nguyên.")
            line_values[line.id] = {
                "price_unit": price or 0.0,
                "vat": vat,
                "delivery_days": days,
                "vendor_note": (post.get(f"note_{line.id}") or "").strip()[:LINE_NOTE_MAX],
                "unavailable": bool(post.get(f"na_{line.id}")),
            }
        return line_values, errors

    def _render_login(self, access, error=None, next_url=""):
        return self._render("hlv_vendor_quotation.portal_login", access, {
            "error": error,
            "next_url": next_url or request.httprequest.full_path.rstrip("?"),
        })

    def _render(self, template, access, values=None):
        context = {
            # QWeb không tự in doctype; thiếu nó trình duyệt chạy quirks mode, vỡ layout mobile.
            "doctype": Markup("<!DOCTYPE html>"),
            "access": access,
            "vendor": access.partner_id,
            "company": request.env.company.sudo(),
            "portal_base": f"{PORTAL_ROUTE}/{access.access_token}",
            "fmt": format_vn_number,
            "vat_options": VAT_SELECTION,
            "post": {},
            "errors": [],
            # Số trên tab "Đơn mua hàng" ở mọi trang của NCC.
            "order_count": len(access._vendor_purchase_orders()),
        }
        context.update(values or {})
        return request.render(template, context)

    def _not_found(self):
        return request.render(
            "hlv_vendor_quotation.portal_not_found",
            {"doctype": Markup("<!DOCTYPE html>"), "company": request.env.company.sudo()},
            status=404,
        )
