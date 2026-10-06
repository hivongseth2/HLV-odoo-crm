# -*- coding: utf-8 -*-
"""Link công khai cho NCC: đăng nhập bằng mật khẩu, xem và điền các yêu cầu báo giá."""

import hmac

from markupsafe import Markup
from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..models.vendor_quote import VENDOR_VISIBLE_STATES
from ..models.vendor_quote_access import LOCK_MINUTES, PORTAL_ROUTE
from ..models.vendor_quote_line import VAT_SELECTION
from ..models.vendor_quote_utils import format_vn_number, parse_vn_number

SESSION_KEY = "hlv_vendor_quote_logins"
VENDOR_NOTE_MAX = 2000
LINE_NOTE_MAX = 255


class VendorQuotePortal(http.Controller):

    @http.route(f"{PORTAL_ROUTE}/<string:token>", type="http", auth="public", methods=["GET"])
    def portal_home(self, token, **kw):
        access = self._get_access(token)
        if not access:
            return self._not_found()
        if not self._is_logged_in(access):
            return self._render("hlv_vendor_quotation.portal_login", access)
        quotes = access.quote_ids.filtered(lambda q: q.state in VENDOR_VISIBLE_STATES)
        statuses = {quote.id: self._vendor_status(quote) for quote in quotes}
        # Báo giá còn sửa được lên đầu, trong mỗi nhóm báo giá mới nhất lên trước.
        quotes = quotes.sorted(lambda q: (not statuses[q.id][2], -q.id))
        return self._render(
            "hlv_vendor_quotation.portal_quote_list",
            access,
            {"quotes": quotes, "statuses": statuses},
        )

    @http.route(f"{PORTAL_ROUTE}/<string:token>/login", type="http", auth="public", methods=["POST"])
    def portal_login(self, token, password="", **kw):
        access = self._get_access(token)
        if not access:
            return self._not_found()
        result = access._vendor_login(password)
        if result == "ok":
            self._remember_login(access)
            return request.redirect(f"{PORTAL_ROUTE}/{token}")
        error = (
            f"Nhập sai quá nhiều lần. Vui lòng thử lại sau {LOCK_MINUTES} phút."
            if result == "locked"
            else "Mật khẩu không đúng."
        )
        return self._render("hlv_vendor_quotation.portal_login", access, {"error": error})

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
            return request.redirect(f"{PORTAL_ROUTE}/{token}")
        quote = access.quote_ids.filtered(
            lambda q: q.id == quote_id and q.state in VENDOR_VISIBLE_STATES
        )
        if not quote:
            return self._not_found()

        values = {
            "quote": quote,
            "status": self._vendor_status(quote),
            "saved": bool(post.get("saved")),
        }
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
        return self._render("hlv_vendor_quotation.portal_quote_form", access, values)

    # ------------------------------------------------------------------
    def _get_access(self, token):
        if not token:
            return None
        Access = request.env["hlv.vendor.quote.access"].sudo()
        return Access.search([("access_token", "=", token)], limit=1) or None

    def _is_logged_in(self, access):
        saved = (request.session.get(SESSION_KEY) or {}).get(str(access.id), "")
        return hmac.compare_digest(saved.encode(), access._session_key().encode())

    def _remember_login(self, access):
        # Gán lại cả dict: session của Odoo chỉ biết "đã đổi" khi gán key, không khi sửa dict lồng.
        logins = dict(request.session.get(SESSION_KEY) or {})
        logins[str(access.id)] = access._session_key()
        request.session[SESSION_KEY] = logins

    def _vendor_status(self, quote):
        """(nhãn, lớp css, NCC còn sửa được không) — nhãn theo góc nhìn của NCC."""
        is_open = quote._is_open_for_vendor()
        if quote.state == "done":
            return ("Đã đóng", "closed", False)
        if not is_open:
            return ("Hết hạn", "closed", False)
        if quote.state == "quoted":
            return ("Đã gửi giá", "quoted", True)
        return ("Chờ báo giá", "waiting", True)

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
        }
        context.update(values or {})
        return request.render(template, context)

    def _not_found(self):
        return request.render(
            "hlv_vendor_quotation.portal_not_found",
            {"doctype": Markup("<!DOCTYPE html>"), "company": request.env.company.sudo()},
            status=404,
        )
