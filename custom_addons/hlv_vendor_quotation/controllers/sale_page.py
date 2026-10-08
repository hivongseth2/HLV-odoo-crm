# -*- coding: utf-8 -*-
"""Trang /hoi-gia-ncc: sale hỏi giá NCC theo SẢN PHẨM, so giá, chọn NCC, lên YCMH.

Cùng kiểu /sale_plan, /delivery_plan: trang riêng ngoài backend, đăng nhập Odoo. Mỗi sale
chỉ thấy phiếu của mã sale mình (?t=<token>, xem services/sale_scope.py). Chạy bằng quyền
user đăng nhập (không sudo); chỗ nào cần sudo đã ghi lý do tại chỗ.

File này: trang, danh sách / chi tiết phiếu và các thao tác trên phiếu. Tạo phiếu và các ô
tìm (sản phẩm, NCC, đơn bán) ở sale_page_create.py.
"""

import base64
import binascii
from collections import defaultdict
from urllib.parse import urlencode

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.osv import expression
from odoo.http import request

from ..models.vendor_inquiry import CLOSE_REASONS, SALE_STATUS
from ..models.vendor_quote_access import SALE_PAGE_ROUTE
from ..models.vendor_quote_line import VAT_SELECTION
from ..models.vendor_quote_utils import local_date_text, paginate
from ..services import sale_page_payload as payload
from ..services import sale_scope
from ..services.asset_version import asset_version
from ..services.chat_bus import SALE_ALL_CHANNEL, bus_version, sale_channel
from ..services.chat_read import mark_seen
from ..services.vendor_chat import FILE_MAX_BYTES, chat_attachment, chat_messages, post_chat
from .sale_page_common import API, SalePageMixin, to_int

PER_PAGE = 30
STATUS_TABS = [("all", "Tất cả")] + SALE_STATUS


class VendorQuoteSalePage(SalePageMixin, http.Controller):

    @http.route(SALE_PAGE_ROUTE, type="http", auth="user", methods=["GET"])
    def sale_page(self, ncc=None, **kw):
        return request.render("hlv_vendor_quotation.sale_page", {
            "asset_version": asset_version(),
            "allowed": self._allowed(),
            "initial_vendor_id": to_int(ncc),
        })

    @http.route(f"{API}/config", type="json", auth="user", methods=["POST"])
    def api_config(self, **kw):
        self._check()
        env = request.env
        codes = sale_scope.sale_code_options(env)
        return {
            "codes": codes,
            "can_see_all": sale_scope.can_see_all(env),
            "all_code": sale_scope.ALL_SALES,
            "vat_options": VAT_SELECTION,
            "status_tabs": STATUS_TABS,
            # Lý do sale chọn khi đóng "Không mua" ("auto" chỉ cron dùng).
            "close_reasons": [r for r in CLOSE_REASONS if r[0] != "auto"],
            # Ngày VN cố định — tài khoản dùng chung hay để trống múi giờ, context_today ra ngày UTC.
            "today": local_date_text(fields.Datetime.now(), "%Y-%m-%d"),
            # Kênh websocket báo tin trao đổi mới — tên kênh do server đặt, JS không tự ghép.
            "bus": {
                "version": bus_version(),
                "all_channel": SALE_ALL_CHANNEL if sale_scope.can_see_all(env) else None,
                "channels": {c["code"]: sale_channel(env, c["code"]) for c in codes},
            },
        }

    @http.route(f"{API}/vendors", type="json", auth="user", methods=["POST"])
    def api_vendors(self, code="", search="", include_id=None, **kw):
        """NCC đã được hỏi giá trong phạm vi mã sale đang xem (không phải cả danh bạ NCC)."""
        scope = self._check(code)
        env = request.env
        counts = defaultdict(dict)
        for access, state, count in env["hlv.vendor.quote"]._read_group(
            sale_scope.scope_domain(scope, "inquiry_id.sale_code") + [("inquiry_id", "!=", False)],
            ["access_id", "state"], ["__count"],
        ):
            if access:
                counts[access.partner_id.id][state] = count
        partners = env["res.partner"].browse(list(counts)).exists()
        include = env["res.partner"].browse(to_int(include_id)).exists()
        partners |= include
        search = (search or "").strip().lower()
        if search:
            partners = partners.filtered(lambda p: search in (p.display_name or "").lower())
        Access = env["hlv.vendor.quote.access"]
        accesses = {a.partner_id.id: a for a in Access.search([("partner_id", "in", partners.ids)])}
        vendors = [
            payload.vendor_summary(p, accesses.get(p.id, Access), counts.get(p.id, {}))
            for p in partners
        ]
        vendors.sort(key=lambda v: (-v["quoted"], -v["waiting"], -v["total"], v["name"].lower()))
        return {"vendors": vendors}

    @http.route(f"{API}/inquiries", type="json", auth="user", methods=["POST"])
    def api_inquiries(self, code="", vendor_id=None, status="all", search="", page=1, **kw):
        scope = self._check(code)
        Inquiry = request.env["hlv.vendor.inquiry"]
        base = sale_scope.scope_domain(scope) + self._search_domain(search)
        if to_int(vendor_id):
            base.append(("quote_ids.access_id.partner_id", "=", to_int(vendor_id)))
        counts = {key: Inquiry.search_count(base + self._status_domain(key)) for key, _label in STATUS_TABS}
        status = status if status in counts else "all"
        pager = paginate(counts[status], page, PER_PAGE)
        inquiries = Inquiry.search(
            base + self._status_domain(status), order="id desc",
            offset=pager["offset"], limit=pager["limit"],
        )
        return {
            "inquiries": [payload.inquiry_summary(i) for i in inquiries],
            "counts": counts,
            "status": status,
            "pager": pager,
        }

    @http.route(f"{API}/inquiry", type="json", auth="user", methods=["POST"])
    def api_inquiry(self, code="", inquiry_id=None, **kw):
        scope = self._check(code)
        return payload.inquiry_detail(self._get_inquiry(inquiry_id, scope))

    @http.route(f"{API}/choose", type="json", auth="user", methods=["POST"])
    def api_choose(self, code="", quote_line_id=None, choose=True, **kw):
        """Sale chọn (hoặc bỏ chọn) giá của một NCC cho một sản phẩm trong phiếu."""
        scope = self._check(code)
        line = request.env["hlv.vendor.quote.line"].browse(to_int(quote_line_id)).exists()
        if not line or not line.inquiry_line_id:
            raise UserError("Không tìm thấy dòng báo giá.")
        inquiry = self._get_inquiry(line.inquiry_line_id.inquiry_id.id, scope)
        if choose:
            line.action_choose()
        else:
            line.action_unchoose()
        return payload.inquiry_detail(inquiry)

    @http.route(f"{API}/create_request", type="json", auth="user", methods=["POST"])
    def api_create_request(self, code="", inquiry_id=None, sale_order_id=None, **kw):
        """Lên YCMH từ các NCC đã chọn. Đơn bán tuỳ chọn — có thì gộp vào YCMH chưa duyệt của đơn."""
        scope = self._check(code)
        inquiry = self._get_inquiry(inquiry_id, scope)
        order = request.env["sale.order"].browse(to_int(sale_order_id)).exists()
        request_record, merged = inquiry.action_create_request(order or None)
        return dict(payload.inquiry_detail(inquiry), request_result={
            "name": request_record.sudo().name, "merged": merged,
        })

    @http.route(f"{API}/cancel", type="json", auth="user", methods=["POST"])
    def api_cancel(self, code="", inquiry_id=None, **kw):
        scope = self._check(code)
        inquiry = self._get_inquiry(inquiry_id, scope)
        inquiry.action_cancel()
        return payload.inquiry_detail(inquiry)

    @http.route(f"{API}/close", type="json", auth="user", methods=["POST"])
    def api_close(self, code="", inquiry_id=None, reason="", note="", **kw):
        """Đóng phiếu "Không mua" (khách không lấy…): giá NCC vẫn giữ cho phiếu sau dùng lại."""
        scope = self._check(code)
        inquiry = self._get_inquiry(inquiry_id, scope)
        inquiry.action_close(reason, note)
        return payload.inquiry_detail(inquiry)

    @http.route(f"{API}/purchase_order", type="json", auth="user", methods=["POST"])
    def api_purchase_order(self, code="", order_id=None, **kw):
        """Xem đơn mua sinh ra từ phiếu (chỉ đọc). Cùng phạm vi kiểm như trao đổi trên đơn mua."""
        order = self._chat_record("order", order_id, self._check(code))
        return payload.purchase_order_detail(order)

    @http.route(f"{API}/vendor_info", type="json", auth="user", methods=["POST"])
    def api_vendor_info(self, code="", quote_id=None, **kw):
        """Thông tin + link / mật khẩu của NCC trên một báo giá trong phạm vi mã sale."""
        return payload.vendor_info(self._chat_record("quote", quote_id, self._check(code)))

    @http.route(f"{API}/po_origin", type="json", auth="user", methods=["POST"])
    def api_po_origin(self, code="", order_ids=None, origin="", **kw):
        """Sale ghi mã đơn hàng của khách vào Tài liệu gốc của các đơn mua (một đơn trong hộp
        xem đơn mua, hoặc mọi đơn của phiếu). Mỗi đơn kiểm phạm vi như xem đơn mua."""
        scope = self._check(code)
        orders = [self._chat_record("order", order_id, scope) for order_id in (order_ids or [])]
        if not orders:
            raise UserError("Chưa chọn đơn mua.")
        for order in orders:
            order._hlv_set_origin(origin)
        return {"orders": [payload.purchase_order_payload(order) for order in orders]}

    @http.route(f"{API}/chat", type="json", auth="user", methods=["POST"])
    def api_chat(self, code="", model="", res_id=None, **kw):
        """Tin trao đổi với NCC trên một báo giá (model="quote") hoặc đơn mua ("order")."""
        record = self._chat_record(model, res_id, self._check(code))
        mark_seen([record], request.env.user)
        return {"title": record.name, "messages": chat_messages(record, self._file_url(code))}

    @http.route(f"{API}/chat_post", type="json", auth="user", methods=["POST"])
    def api_chat_post(self, code="", model="", res_id=None, body="", files=None, **kw):
        """files: [{name, data (base64)}] — trang gửi kèm trong JSON cho khỏi tách form upload."""
        scope = self._check(code)
        record = self._chat_record(model, res_id, scope)
        # scope: mã sale đã kiểm (False ở chế độ "tất cả" — không gán cho sale nào).
        post_chat(record, body, request.env.user.partner_id, from_vendor=False,
                  files=self._decode_files(files or []), sale_code=scope or "")
        mark_seen([record], request.env.user)
        return {"title": record.name, "messages": chat_messages(record, self._file_url(code))}

    @http.route(f"{SALE_PAGE_ROUTE}/tep/<int:attachment_id>", type="http", auth="user", methods=["GET"])
    def chat_file(self, attachment_id, code="", **kw):
        """Tải tệp đính kèm tin trao đổi — chỉ khi cuộc trao đổi thuộc phạm vi mã sale đang xem."""
        attachment, record = chat_attachment(request.env, attachment_id)
        if not record:
            return request.not_found()
        try:
            self._chat_record(
                "quote" if record._name == "hlv.vendor.quote" else "order", record.id, self._check(code)
            )
        except UserError:
            return request.not_found()
        inline = (attachment.mimetype or "").startswith("image/") or attachment.mimetype == "application/pdf"
        return request.env["ir.binary"]._get_stream_from(attachment).get_response(as_attachment=not inline)

    # ------------------------------------------------------------------
    def _file_url(self, code):
        return lambda attachment_id: f"{SALE_PAGE_ROUTE}/tep/{attachment_id}?{urlencode({'code': code})}"

    def _decode_files(self, files):
        """[{name, data base64}] → [(tên, bytes)]. Chặn cỡ trước khi giải mã cho đỡ tốn bộ nhớ."""
        decoded = []
        for item in files:
            data = item.get("data") or ""
            if len(data) * 3 // 4 > FILE_MAX_BYTES + 3:
                raise UserError(f"Tệp \"{item.get('name')}\" quá {FILE_MAX_BYTES // (1024 * 1024)}MB.")
            try:
                decoded.append((item.get("name") or "", base64.b64decode(data, validate=True)))
            except (binascii.Error, ValueError):
                raise UserError(f"Không đọc được tệp \"{item.get('name')}\".") from None
        return decoded

    def _chat_record(self, model, res_id, scope):
        """Báo giá / đơn mua thuộc một phiếu trong phạm vi mã sale đã kiểm — không cho mở cuộc
        trao đổi của sale khác bằng id. Đơn mua trả về bằng sudo (sale không có quyền đơn mua)."""
        if model == "quote":
            quote = request.env["hlv.vendor.quote"].browse(to_int(res_id)).exists()
            if quote and quote.inquiry_id:
                self._get_inquiry(quote.inquiry_id.id, scope)
                return quote
        elif model == "order":
            order = request.env["purchase.order"].sudo().browse(to_int(res_id)).exists()
            inquiries = order.hlv_inquiry_ids if order else request.env["hlv.vendor.inquiry"]
            if inquiries.filtered(lambda i: not scope or (i.sale_code or "").upper() == scope.upper()):
                return order
        raise UserError("Không tìm thấy cuộc trao đổi.")

    def _search_domain(self, search):
        search = (search or "").strip()
        if not search:
            return []
        return expression.OR([
            [("name", "ilike", search)],
            [("sale_code", "ilike", search)],
            [("sale_order_id.name", "ilike", search)],
            [("request_id.name", "ilike", search)],
            [("line_ids.product_id", "ilike", search)],
            [("quote_ids.partner_id", "ilike", search)],
        ])

    def _status_domain(self, status):
        if status == "all":
            # "Tất cả" = phiếu còn theo dõi; phiếu đã đóng / huỷ xem ở tab riêng.
            return [("sale_status", "not in", ("cancel", "closed"))]
        return [("sale_status", "=", status)]
