# -*- coding: utf-8 -*-
"""Link công khai cho NCC: đăng nhập bằng mật khẩu, xem và điền các yêu cầu báo giá."""

import hmac
from urllib.parse import urlencode

from markupsafe import Markup
from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request

from ..models.vendor_quote import VENDOR_STATUSES, VENDOR_VISIBLE_STATES
from ..models.vendor_quote_access import LOCK_MINUTES, PORTAL_ROUTE
from ..models.vendor_quote_line import DEFAULT_VENDOR_VAT, VAT_SELECTION
from ..models.vendor_quote_utils import (
    deadline_hint, default_price_valid_until, format_vn_number, local_date_text, paginate, parse_vn_number,
    split_code_name, split_unit_price,
)
from ..services.asset_version import asset_version
from ..services.chat_bus import bus_version, vendor_channel
from ..services.chat_read import mark_seen
from ..services.price_reuse import REFERENCE_DAYS, reference_prices
from ..services.vendor_feed import row_marks, vendor_feed
from ..services.vendor_chat import chat_attachment, chat_messages, post_chat

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
    def portal_home(self, token, status=None, q="", page=1, **kw):
        access = self._get_access(token)
        if not access:
            return self._not_found()
        if not self._is_logged_in(access):
            return self._render_login(access)

        q = (q or "").strip()[:SEARCH_MAX]
        Quote = request.env["hlv.vendor.quote"].sudo()
        base_domain = self._list_domain(access, q)
        counts = {"all": Quote.search_count(base_domain)}
        for key in VENDOR_STATUSES:
            counts[key] = Quote.search_count(base_domain + Quote._vendor_status_domain(key))
        if status not in STATUS_DISPLAY:
            # Mở trang chưa chọn tab: ưu tiên "Chờ báo giá" — việc NCC cần làm; hết thì xem tất cả.
            status = "waiting" if counts["waiting"] else "all"

        domain = base_domain if status == "all" else base_domain + Quote._vendor_status_domain(status)
        pager = paginate(counts[status], page, PER_PAGE)
        quotes = Quote.search(domain, order="id desc", offset=pager["offset"], limit=pager["limit"])
        return self._render("hlv_vendor_quotation.portal_quote_list", access, {
            "quotes": quotes,
            "statuses": {quote.id: STATUS_DISPLAY[quote._vendor_status()] for quote in quotes},
            "hints": {quote.id: deadline_hint(quote.date_deadline, Quote._vendor_today()) for quote in quotes},
            # Đơn mua sinh ra từ từng báo giá — NCC thấy hỏi giá nào đã thành đơn.
            "quote_orders": {quote.id: quote._vendor_purchase_orders() for quote in quotes},
            # Dòng có tin bên mua chưa xem / báo giá chưa mở lần nào.
            "marks": row_marks(quotes, access),
            # "Tên – SĐT" sale hỏi giá, hiện ở khung xem nhanh.
            "requesters": {
                quote.id: request.env["hlv.vendor.sale.contact"]._requester(quote.inquiry_id.sale_code)
                for quote in quotes
            },
            "active_tab": "quotes",
            "tabs": [
                (key, STATUS_DISPLAY[key][0], counts[key], self._list_url(access, key, q))
                for key in VENDOR_STATUSES + ("all",)
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
        if not access._password_required():
            return request.redirect(self._safe_next(access, next_url))
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

    @http.route(f"{PORTAL_ROUTE}/<string:token>/thong-bao/da-xem", type="http", auth="public", methods=["POST"])
    def portal_mark_all_seen(self, token, next_url="", **kw):
        """Nút "Đánh dấu đã xem hết" trong thông báo: mọi báo giá + đơn mua của NCC này."""
        access = self._get_access(token)
        if not access or not self._is_logged_in(access):
            return self._not_found()
        quotes = access.quote_ids.filtered(lambda q: q.state in VENDOR_VISIBLE_STATES)
        mark_seen(list(quotes) + list(access._vendor_purchase_orders()), access)
        return request.redirect(self._safe_next(access, next_url))

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
        # Mở trang là đã xem báo giá + mọi tin hiện có (trước _render để thông báo tính đúng).
        mark_seen([quote], access)

        values = {"quote": quote, "saved": bool(post.get("saved"))}
        if request.httprequest.method == "POST":
            line_values, errors = self._read_quote_form(quote, post)
            valid_until = self._read_valid_until(post, errors)
            if not errors:
                try:
                    quote._vendor_submit(line_values, (post.get("vendor_note") or "")[:VENDOR_NOTE_MAX], valid_until)
                except UserError as exc:
                    errors = [exc.args[0]]
                else:
                    return request.redirect(f"{PORTAL_ROUTE}/{token}/{quote.id}?saved=1")
            values.update(post=post, errors=errors, saved=False)
        today = quote._vendor_today()
        values.update(
            today_iso=today.isoformat(),
            # Dòng chưa có giá mà NCC đã báo trong 7 ngày: điền sẵn giá đó — NCC kiểm rồi gửi.
            references=reference_prices(quote) if quote._is_open_for_vendor() else {},
            reference_days=REFERENCE_DAYS,
            default_valid_iso=default_price_valid_until(today).isoformat(),
            status=STATUS_DISPLAY[quote._vendor_status()],
            editable=quote._is_open_for_vendor(),
            fully_ordered=quote._fully_ordered(),
            hint=deadline_hint(quote.date_deadline, quote._vendor_today()),
            company=quote.company_id or request.env.company.sudo(),
            orders=quote._vendor_purchase_orders(),
            chat=chat_messages(quote, self._file_url(token)),
            chat_key=f"quote:{quote.id}",
            chat_doc=quote.name,
            chat_url=f"{PORTAL_ROUTE}/{token}/{quote.id}/tin-nhan",
            chat_error=post.get("chat_error") if request.httprequest.method == "GET" else "",
            # Sale đã chọn NCC cho mặt hàng nào: "selected" = chọn mình, "other" = chọn NCC
            # khác, "" = chưa chọn ai — để NCC biết dòng nào đã được đặt.
            line_choice={line.id: self._line_choice(line) for line in quote.line_ids},
            requester=self._requester(quote),
        )
        return self._render("hlv_vendor_quotation.portal_quote_form", access, values)

    @staticmethod
    def _requester(quote):
        """Sale hỏi giá để NCC biết ai hỏi, gọi số nào: {"name", "phone"}; báo giá không gắn phiếu
        hỏi giá / phiếu chưa có mã sale → None. Mã chưa có trong danh bạ → tên là mã."""
        code = (quote.inquiry_id.sale_code or "").strip()
        if not code:
            return None
        info = request.env["hlv.vendor.sale.contact"]._for_code(code)
        return info or {"name": code, "phone": ""}

    @http.route(
        f"{PORTAL_ROUTE}/<string:token>/<int:quote_id>/tin-nhan",
        type="http",
        auth="public",
        methods=["POST"],
    )
    def portal_quote_chat(self, token, quote_id, message="", **kw):
        """NCC nhắn cho bên mua trên một báo giá."""
        access = self._get_access(token)
        if not access or not self._is_logged_in(access):
            return self._not_found()
        quote = self._get_quote(access, quote_id)
        if not quote:
            return self._not_found()
        return self._post_vendor_chat(
            quote, access, message, quote._chat_contacts(), f"{PORTAL_ROUTE}/{token}/{quote.id}"
        )

    @http.route(
        f"{PORTAL_ROUTE}/<string:token>/tep/<int:attachment_id>",
        type="http",
        auth="public",
        methods=["GET"],
    )
    def portal_chat_file(self, token, attachment_id, **kw):
        """Tải tệp đính kèm tin trao đổi — chỉ tệp trên báo giá / đơn mua của chính NCC này."""
        access = self._get_access(token)
        if not access or not self._is_logged_in(access):
            return request.not_found()
        attachment, record = chat_attachment(request.env, attachment_id)
        allowed = record and (
            (record._name == "hlv.vendor.quote" and record.access_id == access)
            or (record._name == "purchase.order" and record in access._vendor_purchase_orders())
        )
        if not allowed:
            return request.not_found()
        return self._file_response(attachment)

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
    def _line_choice(self, line):
        """"selected" = bên mua chọn / đang đặt hàng của NCC này cho mặt hàng (kể cả khi phần
        còn thiếu đã chuyển NCC khác); "other" = chọn NCC khác; "" = chưa chọn ai."""
        if line.selection_state == "selected" or line._hlv_ordered_from_vendor():
            return "selected"
        return "other" if line.selection_state == "other" else ""

    def _file_url(self, token):
        return lambda attachment_id: f"{PORTAL_ROUTE}/{token}/tep/{attachment_id}"

    def _uploaded_files(self):
        """Tệp NCC chọn ở ô "Đính kèm" của form trao đổi → list (tên, bytes)."""
        return [
            (upload.filename, upload.read())
            for upload in request.httprequest.files.getlist("attachments")
            if upload.filename
        ]

    def _post_vendor_chat(self, record, access, message, notify_partners, back_url, back_params=None):
        """Đăng tin NCC gửi (kèm tệp nếu có) rồi quay lại trang. Tệp sai → báo lỗi trên trang.

        back_params: tham số giữ lại khi quay về (vd. from= của breadcrumb).
        """
        params = dict(back_params or {})
        try:
            post_chat(record, message, access.partner_id, from_vendor=True,
                      notify_partners=notify_partners, files=self._uploaded_files())
        except UserError as exc:
            params["chat_error"] = exc.args[0]
        query = f"?{urlencode(params)}" if params else ""
        return request.redirect(f"{back_url}{query}#trao-doi")

    def _file_response(self, attachment):
        # Ảnh / PDF mở thẳng trên trình duyệt; tệp khác tải về.
        inline = (attachment.mimetype or "").startswith("image/") or attachment.mimetype == "application/pdf"
        return request.env["ir.binary"]._get_stream_from(attachment).get_response(as_attachment=not inline)

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

    def _list_url(self, access, status=None, q="", page=1):
        # Luôn ghi status (kể cả "all"): thiếu status là trang tự chọn tab "Chờ báo giá".
        params = {"status": status, "q": q or None, "page": page if page > 1 else None}
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
        if not access._password_required():
            return True  # đang tắt mật khẩu: có link là vào
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
        use_discount = bool(post.get("use_discount"))
        line_values, errors = {}, []
        for index, line in enumerate(quote.line_ids, start=1):
            def number(field, label):
                return self._read_line_number(post, f"{field}_{line.id}", f"Dòng {index}: không đọc được {label}", errors)

            vat = post.get(f"vat_{line.id}") or False
            if vat and vat not in valid_vat:
                vat = False
            # Bật "Có chiết khấu" mà để trống % của dòng = 0%.
            discount = (number("disc", "% chiết khấu") or 0.0) if use_discount else None
            if discount is not None and discount >= 100:
                errors.append(f"Dòng {index}: chiết khấu phải nhỏ hơn 100%.")
                discount = 0.0
            # NCC chỉ gõ một ô: đơn giá đã gồm VAT (có chiết khấu thì là giá trước CK). Giá chưa VAT
            # — giá lưu và đem so — tính ở đây, không tin số nào JS gửi lên.
            price, list_price = split_unit_price(
                number("unit", "đơn giá"), float(vat) if vat and vat != "kct" else 0.0, discount,
            )
            raw_days = (post.get(f"days_{line.id}") or "").strip()
            days = int(raw_days) if raw_days.isdigit() else 0
            if raw_days and not raw_days.isdigit():
                errors.append(f"Dòng {index}: số ngày giao \"{raw_days}\" phải là số nguyên.")
            line_values[line.id] = {
                "price_unit": price or 0.0,
                # Chỉ có khi NCC bật "Có chiết khấu"; tắt đi là xoá số cũ.
                "list_price": list_price,
                "discount": discount or 0.0,
                "vat": vat,
                "delivery_days": days,
                "vendor_note": (post.get(f"note_{line.id}") or "").strip()[:LINE_NOTE_MAX],
                "invoice_name": (post.get(f"inv_{line.id}") or "").strip()[:LINE_NOTE_MAX],
                "unavailable": bool(post.get(f"na_{line.id}")),
            }
        return line_values, errors

    @staticmethod
    def _read_line_number(post, key, label, errors):
        """Số trong ô `key` của form; trống → None; gõ sai → None và thêm lỗi `label "chữ đã gõ".`"""
        raw = (post.get(key) or "").strip()
        value = parse_vn_number(raw)
        if raw and value is None:
            errors.append(f"{label} \"{raw}\".")
        return value

    def _read_valid_until(self, post, errors):
        """Ô "Giá có hiệu lực đến" (yyyy-mm-dd từ input date). Trống → False (model lấy mặc định
        7 ngày); sai định dạng → thêm lỗi, trả False."""
        raw = (post.get("price_valid_until") or "").strip()
        if not raw:
            return False
        try:
            return fields.Date.to_date(raw)
        except ValueError:
            errors.append(f"Không đọc được ngày giá hiệu lực \"{raw}\".")
            return False

    def _render_login(self, access, error=None, next_url=""):
        return self._render("hlv_vendor_quotation.portal_login", access, {
            "error": error,
            "next_url": next_url or request.httprequest.full_path.rstrip("?"),
        })

    def _render(self, template, access, values=None):
        context = {
            # QWeb không tự in doctype; thiếu nó trình duyệt chạy quirks mode, vỡ layout mobile.
            "doctype": Markup("<!DOCTYPE html>"),
            "asset_version": asset_version(),
            # Kênh websocket của NCC: đặt theo mã link bí mật (xem services/chat_bus.py).
            "bus_channel": vendor_channel(access),
            "bus_version": bus_version(),
            "access": access,
            "password_required": access._password_required(),
            "vendor": access.partner_id,
            "company": request.env.company.sudo(),
            "portal_base": f"{PORTAL_ROUTE}/{access.access_token}",
            "fmt": format_vn_number,
            # Mã hàng và tên hàng hiện thành hai cột: bỏ tiền tố "[mã]" khỏi tên.
            "code_name": split_code_name,
            # Ngày giờ theo giờ VN — Datetime Odoo lưu UTC, strftime thẳng sẽ lệch ngày.
            "fdate": local_date_text,
            "vat_options": VAT_SELECTION,
            "default_vat": DEFAULT_VENDOR_VAT,
            "post": {},
            "errors": [],
            # Số trên hai tab "Yêu cầu báo giá" / "Đơn mua hàng" ở mọi trang của NCC.
            "quote_count": len(access.quote_ids.filtered(lambda q: q.state in VENDOR_VISIBLE_STATES)),
            "order_count": len(access._vendor_purchase_orders()),
        }
        if self._is_logged_in(access):
            context["feed"] = vendor_feed(access, context["portal_base"])
        context.update(values or {})
        return request.render(template, context)

    def _not_found(self):
        return request.render(
            "hlv_vendor_quotation.portal_not_found",
            {
                "doctype": Markup("<!DOCTYPE html>"),
                "asset_version": asset_version(),
                "company": request.env.company.sudo(),
            },
            status=404,
        )
