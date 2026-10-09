# -*- coding: utf-8 -*-
"""Trang "Báo giá theo mặt hàng" của NCC — trang mặc định khi mở link.

NCC quen báo giá theo danh sách hàng chứ không theo từng phiếu: trang này trải mọi mặt hàng
của các yêu cầu báo giá còn mở thành MỘT bảng (cột "Phiếu" cho biết hàng thuộc yêu cầu nào),
điền một lần rồi gửi. Bấm Gửi: phiếu nào điền đủ và có thay đổi thì gửi (_vendor_submit — cùng
luật với trang từng phiếu), phiếu còn thiếu thì báo lại đúng phiếu đó, số đã gõ vẫn giữ.

Trang theo phiếu cũ vẫn nguyên ở /bao-gia/<link>/phieu (và link cũ có ?status=…).
Kế thừa VendorQuotePortal để dùng chung đăng nhập, khung trang, đọc form — không chép lại.
"""

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..models.vendor_quote_access import PORTAL_ROUTE
from ..models.vendor_quote_utils import (
    deadline_hint,
    default_price_valid_until,
    line_values_changed,
    split_code_name,
)
from ..services.price_reuse import REFERENCE_DAYS, reference_prices
from .vendor_portal import VendorQuotePortal

QUOTES = "phieu"
# Trường dòng NCC điền — so với giá trị đang lưu để biết phiếu nào NCC có sửa. Không so list_price:
# nó suy ra từ đơn giá + %CK (bật "Có chiết khấu" để 0% cũng ghi list_price) — NCC không sửa giá.
LINE_FIELDS = ("price_unit", "discount", "vat", "delivery_days", "vendor_note", "invoice_name", "unavailable")
# Phiếu chờ báo giá: chỉ coi là NCC "có báo" khi giá / hết hàng khác số điền sẵn.
PRICE_FIELDS = ("price_unit", "unavailable")
NAME_MAX = 40


class VendorLineBoardPortal(VendorQuotePortal):

    @http.route()
    def portal_home(self, token, status=None, q="", page=1, **kw):
        # Có lọc / tìm / trang → đang dùng danh sách theo phiếu (link cũ, bookmark): giữ nguyên.
        if status is not None or q or str(page) != "1":
            return super().portal_home(token, status=status, q=q, page=page, **kw)
        return self.portal_line_board(token, **kw)

    @http.route(f"{PORTAL_ROUTE}/<string:token>/{QUOTES}", type="http", auth="public", methods=["GET"])
    def portal_quote_list(self, token, status=None, q="", page=1, **kw):
        # status "" = để trang tự chọn tab (ưu tiên "Chờ báo giá"), xem VendorQuotePortal.portal_home.
        return super().portal_home(token, status=status or "", q=q, page=page, **kw)

    @http.route(f"{PORTAL_ROUTE}/<string:token>/mat-hang", type="http", auth="public", methods=["GET", "POST"])
    def portal_line_board(self, token, show=None, **post):
        access = self._get_access(token)
        if not access:
            return self._not_found()
        if not self._is_logged_in(access):
            return self._render_login(access)
        quotes = self._open_quotes(access)
        raw_saved = str(post.get("saved") or "")
        values = {"saved_count": int(raw_saved) if raw_saved.isdigit() else 0, "error_line_ids": set()}
        if request.httprequest.method == "POST":
            saved, errors, error_line_ids = self._submit_board(quotes, post)
            if not errors:
                return request.redirect(f"{PORTAL_ROUTE}/{token}?saved={saved}")
            values.update(post=post, errors=errors, error_line_ids=error_line_ids, saved_count=saved)
            quotes = self._open_quotes(access)

        pending = quotes.filtered(lambda q: q.state == "sent")
        show = show if show in ("pending", "all") else ("pending" if pending else "all")
        shown = pending if show == "pending" else quotes
        lines = shown.mapped("line_ids").filtered(lambda line: not line.vendor_locked)
        today = request.env["hlv.vendor.quote"].sudo()._vendor_today()
        references = {}
        for quote in shown:
            references.update(reference_prices(quote))
        values.update(
            active_tab="lines",
            show=show,
            pending_quote_count=len(pending),
            open_quote_count=len(quotes),
            # Hạn gần trước, rồi theo phiếu, rồi đúng thứ tự dòng trong phiếu.
            lines=lines.sorted(lambda line: (line.quote_id.date_deadline or today, line.quote_id.id, line.sequence, line.id)),
            editable=True,
            references=references,
            reference_days=REFERENCE_DAYS,
            line_choice={line.id: self._line_choice(line) for line in lines},
            quote_info={quote.id: self._quote_info(quote, today) for quote in shown},
            today_iso=today.isoformat(),
            default_valid_iso=default_price_valid_until(today).isoformat(),
        )
        return self._render("hlv_vendor_quotation.portal_line_board", access, values)

    def _open_quotes(self, access):
        """Yêu cầu báo giá NCC còn sửa được (chờ báo giá / đã gửi, chưa hết hạn, còn hàng chưa đặt)."""
        quotes = request.env["hlv.vendor.quote"].sudo().search(self._list_domain(access, ""), order="date_deadline, id")
        return quotes.filtered(lambda q: q._is_open_for_vendor())

    def _quote_info(self, quote, today):
        requester = self._requester(quote)
        hint = deadline_hint(quote.date_deadline, today)
        return {
            "url": f"{PORTAL_ROUTE}/{quote.access_id.access_token}/{quote.id}",
            "deadline": quote.date_deadline.strftime("%d/%m") if quote.date_deadline else "",
            "title": " · ".join(part for part in (
                quote.name,
                f"Hạn {quote.date_deadline.strftime('%d/%m/%Y')}" if quote.date_deadline else "",
                hint[0],
                "Người hỏi giá: %s %s" % (requester["name"], requester["phone"]) if requester else "",
            ) if part).strip(),
            "urgent": hint[1] in ("urgent", "over"),
            "note": quote.note or "",
            # Cột "Người hỏi": {"name", "phone"} hoặc None (báo giá không gắn mã sale).
            "requester": requester,
        }

    @staticmethod
    def _short_name(line):
        name = split_code_name(line.name or line.product_id.name, line.product_id.default_code or "")
        return name if len(name) <= NAME_MAX else f"{name[:NAME_MAX - 1]}…"

    def _submit_board(self, quotes, post):
        """Gửi các phiếu NCC có điền / có sửa trên bảng chung. Trả (số phiếu đã gửi, lỗi, id dòng lỗi).

        Mỗi phiếu một savepoint: phiếu lỗi (thiếu giá / VAT…) không kéo các phiếu khác đã gửi được.
        Phiếu NCC không đụng tới thì bỏ qua — không báo thiếu, không làm mới ngày gửi / hiệu lực giá.
        """
        saved, errors, error_line_ids = 0, [], set()
        valid_until = self._read_valid_until(post, errors)
        if errors:
            return 0, errors, error_line_ids
        for quote in quotes:
            open_lines = quote.line_ids.filtered(lambda line: not line.vendor_locked)
            if not any(f"unit_{line.id}" in post for line in open_lines):
                continue  # phiếu không có trên bảng đang xem
            line_values, read_errors = self._read_quote_form(
                quote, post, lambda _index, line, name=quote.name: f"{name} · {self._short_name(line)}",
            )
            # Gõ sai số (giá "abc"…) thì báo ngay — số không đọc được coi như ô trống, phiếu sẽ bị xem
            # là chưa đụng tới và lỗi bị nuốt mất.
            if read_errors:
                errors += read_errors
                continue
            if not self._board_touched(quote, open_lines, line_values):
                continue
            missing = open_lines.filtered(lambda line: self._missing_vat(line_values[line.id]))
            if missing:
                error_line_ids.update(missing.ids)
                errors.append(
                    f"{quote.name}: có đơn giá nhưng chưa chọn VAT — {', '.join(self._short_name(line) for line in missing)}."
                )
                continue
            try:
                with request.env.cr.savepoint():
                    quote._vendor_submit(line_values, quote.vendor_note or "", valid_until)
            except UserError as exc:
                errors.append(f"{quote.name}: {exc.args[0]}")
            else:
                saved += 1
        if not saved and not errors:
            errors.append("Chưa có giá nào mới để gửi — điền đơn giá hoặc bỏ tick \"Sẵn hàng\" ở mặt hàng không có, rồi bấm Gửi.")
        return saved, errors, error_line_ids

    @staticmethod
    def _missing_vat(values):
        # Cùng luật _vendor_submit: dòng có giá phải có VAT; để trống giá / bỏ tick "Sẵn hàng" = không có hàng.
        return bool(not values["unavailable"] and values["price_unit"] and not values["vat"])

    @staticmethod
    def _line_answered(values):
        # NCC đã trả lời dòng này: có giá, hoặc bỏ tick "Sẵn hàng" (không có hàng).
        return bool(values["unavailable"] or values["price_unit"])

    def _board_touched(self, quote, open_lines, line_values):
        """NCC có báo gì cho phiếu này trên bảng chung không.

        Phiếu đã báo giá: có dòng khác giá trị đang lưu. Phiếu chờ báo giá: mọi dòng đều có giá hoặc
        bỏ tick "Sẵn hàng" (kể cả nhờ giá cũ điền sẵn — giống bấm Gửi ở trang phiếu), hoặc có dòng mà giá / hết hàng
        khác số điền sẵn. Gửi rồi thì dòng để trống thành không có hàng — nên phiếu chỉ có vài dòng
        "giá cũ" NCC chưa đụng tới thì KHÔNG gửi, kẻo các dòng còn lại bị coi là hết hàng.
        """
        if quote.state != "sent":
            return any(
                line_values_changed(
                    {field: line[field] for field in LINE_FIELDS},
                    {field: line_values[line.id][field] for field in LINE_FIELDS},
                )
                for line in open_lines
            )
        if all(self._line_answered(line_values[line.id]) for line in open_lines):
            return True
        references = reference_prices(quote)

        def prefilled(line):
            source = line if (line.price_unit or line.unavailable) else references.get(line.id)
            return {field: source[field] for field in PRICE_FIELDS} if source else {}

        return any(
            line_values_changed(prefilled(line), {field: line_values[line.id][field] for field in PRICE_FIELDS})
            for line in open_lines
        )
