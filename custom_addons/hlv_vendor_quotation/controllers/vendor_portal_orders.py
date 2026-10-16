# -*- coding: utf-8 -*-
"""Tab "Đơn mua hàng" trên link của NCC: đơn mua sinh ra từ báo giá của NCC (trạng thái đơn hiện ra
do admin chọn trong Cài đặt), chia tab theo tiến độ (chờ xác nhận / cần xử lý / chờ nhận hàng / đã
giao / đã hủy), và NCC báo tiến độ trên đơn đã xác nhận — các bước theo phương thức giao hàng thu mua chọn
(PurchaseOrder._hlv_vendor_steps):
- "Xác nhận đơn hàng": NCC bấm;
- "Đã đóng gói": NCC bấm — đơn nhận tại kho NCC (và đơn cũ chưa chọn phương thức);
- "Đã gửi hàng": đơn giao hàng / chành (và đơn cũ gửi CPN / chành) — NCC nhập mã vận đơn hoặc tên chành + số xe;
- "Đã giao": tự chuyển khi kho bên mua nhận đủ hàng — NCC không phải bấm.

Kế thừa VendorQuotePortal (cơ chế mở rộng controller của Odoo) để dùng chung đăng nhập,
khung trang và các hàm phụ — không chép lại.
"""

from urllib.parse import urlencode

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request

from ..models.purchase_order import CONFIRMED_STATES, PROGRESS_LABELS
from ..models.purchase_order_revision import tax_rate_of
from ..models.vendor_quote_access import PORTAL_ORDERS as ORDERS, PORTAL_ROUTE
from ..models.vendor_quote_utils import DELIVERY_CHANH, DELIVERY_CPN, parse_vn_number, price_incl_vat
from ..services.vendor_chat import chat_messages, post_chat
from ..services.vendor_feed import row_marks
from .vendor_portal import VendorQuotePortal

# Tab danh sách đơn mua — khoá trùng PurchaseOrder._hlv_vendor_stage().
ORDER_TABS = [
    ("rfq", "Chờ xác nhận"),
    # Đơn giao hàng / chành không có bước đóng gói — tên tab nói việc, không nói bước.
    ("waiting", "Cần xử lý"),
    ("packed", "Chờ nhận hàng"),
    ("delivered", "Đã giao"),
    ("cancel", "Đã hủy"),
    ("all", "Tất cả"),
]
# Thông báo sau khi lưu (?saved=…): báo tiến độ / gửi yêu cầu thay đổi / áp ngay / chỉ đổi ngày / rút yêu cầu.
SAVED_MESSAGES = {
    "1": "Đã cập nhật tiến độ đơn. Cảm ơn quý công ty!",
    "pending": "Đã gửi yêu cầu thay đổi — bên mua duyệt xong sẽ áp vào đơn và báo quý công ty.",
    "applied": "Đã cập nhật đơn.",
    "dates": "Đã lưu ngày giao — bên mua đã được báo.",
    "withdrawn": "Đã rút yêu cầu thay đổi.",
}
# Bản in cho NCC: mẫu "Đơn mua hàng" chuẩn của Odoo. Mẫu tự dựng cũ (portal_order_print) giữ lại
# trong views/portal_order_templates.xml để dùng lại sau, hiện không route nào gọi.
PRINT_REPORT = "purchase.report_purchaseorder"


class VendorPurchaseOrderPortal(VendorQuotePortal):

    @http.route(f"{PORTAL_ROUTE}/<string:token>/{ORDERS}", type="http", auth="public", methods=["GET"])
    def portal_orders(self, token, stage=None, saved=None, **kw):
        access = self._get_access(token)
        if not access:
            return self._not_found()
        if not self._is_logged_in(access):
            return self._render_login(access, next_url=f"{PORTAL_ROUTE}/{token}/{ORDERS}")
        orders = access._vendor_purchase_orders().sorted(lambda o: o.date_order, reverse=True)
        stages = {order.id: order._hlv_vendor_stage() for order in orders}
        counts = {key: sum(1 for value in stages.values() if value == key) for key, _label in ORDER_TABS}
        counts["all"] = len(orders)
        if stage not in counts:
            # Mở tab chưa chọn: ưu tiên đơn NCC còn việc phải làm.
            stage = "waiting" if counts["waiting"] else "all"
        # Tab "Chờ xác nhận" chỉ khi Cài đặt cho NCC thấy đơn chưa xác nhận (hoặc đang mở tab đó).
        show_rfq = stage == "rfq" or any(
            state not in CONFIRMED_STATES for state in request.env["purchase.order"]._hlv_vendor_visible_states()
        )
        shown = orders if stage == "all" else orders.filtered(lambda o: stages[o.id] == stage)
        list_url = f"{PORTAL_ROUTE}/{token}/{ORDERS}?{urlencode({'stage': stage})}"
        return self._render("hlv_vendor_quotation.portal_order_list", access, {
            "orders": shown,
            "stage": stage,
            "infos": {order.id: self._order_info(order) for order in shown},
            # Cập nhật tiến độ ngay trong khung xem nhanh → về lại đúng tab này.
            "next_url": list_url,
            "saved_order": saved or "",
            "tabs": [
                (key, label, counts[key], f"{PORTAL_ROUTE}/{token}/{ORDERS}?{urlencode({'stage': key})}")
                for key, label in ORDER_TABS
                if key != "rfq" or show_rfq
            ],
            "order_quotes": {order.id: order.hlv_vendor_quote_ids for order in shown},
            "marks": row_marks(shown, access),
            "progress_labels": PROGRESS_LABELS,
            "post": {},
            "active_tab": "orders",
        })

    @staticmethod
    def _read_revision_edits(order, form):
        """Dòng NCC bấm bút chì sửa (edit_<id>): {id dòng: {"qty", "price" (sau VAT), "day"}} — ô trống = không sửa
        ô đó (None). Giá: NCC gõ sau VAT (price_) hoặc chưa VAT (pricenet_, pbasis_=net — đổi ra sau VAT theo thuế
        của dòng). Số / ngày không đọc được → UserError nêu tên hàng."""
        edits = {}
        for line in order.sudo().order_line.filtered(lambda l: not l.display_type):
            if not form.get(f"edit_{line.id}"):
                continue
            name = line.product_id.display_name
            values = {}
            by_net = form.get(f"pbasis_{line.id}") == "net"
            price_key, price_label = ("pricenet", "đơn giá chưa VAT") if by_net else ("price", "đơn giá")
            for key, field, label in (("qty", "qty", "số lượng"), ("price", price_key, price_label)):
                raw = (form.get(f"{field}_{line.id}") or "").strip()
                values[key] = parse_vn_number(raw) if raw else None
                if raw and values[key] is None:
                    raise UserError(f"{name}: không đọc được {label} \"{raw}\".")
            if by_net and values["price"] is not None:
                values["price"] = price_incl_vat(values["price"], tax_rate_of(line))
            raw_day = (form.get(f"day_{line.id}") or "").strip()
            try:
                values["day"] = fields.Date.to_date(raw_day) if raw_day else None
            except ValueError:
                raise UserError(f"{name}: không đọc được ngày giao \"{raw_day}\".") from None
            edits[line.id] = values
        return edits

    @staticmethod
    def _order_info(order):
        """Thông tin một đơn cho trang NCC: tiến độ (các bước + việc NCC cần làm), phương thức / địa điểm giao hàng,
        cách gửi chọn sẵn khi NCC báo đã gửi (đơn giao hàng / chành, hoặc Studio ghi CPN / chành → "Gửi CPN / chành")."""
        mode = DELIVERY_CPN if order.hlv_delivery_method == "ship" else order._hlv_delivery_mode()
        return {
            "progress": order._hlv_vendor_progress(),
            "steps": order._hlv_vendor_steps(),
            "next_action": order._hlv_vendor_next_action(),
            "state_label": order._hlv_vendor_state_label(),
            "delivery_term": order._hlv_delivery_method_text(),
            "delivery_place": order._hlv_delivery_place(),
            "ship_mode": mode if mode in (DELIVERY_CPN, DELIVERY_CHANH) else "",
            "ship_text": order._hlv_ship_text(),
            # Hàng còn chờ giao theo id dòng đơn mua (ngày giao dự kiến, quá hẹn) — chỉ đơn đã xác nhận, chưa hủy.
            "due": {item["line_id"]: item for item in order._hlv_pending_info()} if order.state in CONFIRMED_STATES else {},
            # Yêu cầu thay đổi đơn của NCC (phiên bản): đang chờ duyệt, lịch sử, giá sau VAT từng dòng.
            "revision": order._hlv_revision_info(),
        }

    @http.route(
        f"{PORTAL_ROUTE}/<string:token>/{ORDERS}/<int:order_id>",
        type="http",
        auth="public",
        methods=["GET", "POST"],
    )
    def portal_order(self, token, order_id, status=None, ship=None, revise=None, withdraw=None, **kw):
        access = self._get_access(token)
        if not access:
            return self._not_found()
        if not self._is_logged_in(access):
            return self._render_login(access, next_url=f"{PORTAL_ROUTE}/{token}/{ORDERS}/{order_id}")
        # Chỉ đơn mua sinh ra từ báo giá của chính NCC này — không mở đơn khác bằng id.
        order = access._vendor_purchase_orders().filtered(lambda o: o.id == order_id)
        if not order:
            return self._not_found()
        from_quote = self._from_quote(access, kw.get("from"))
        self._mark_vendor_seen([order], access)
        error = ""
        saved = "1"
        if request.httprequest.method == "POST" and (status or ship or revise or withdraw):
            try:
                if ship:
                    self._mark_shipped(order, access, kw)
                elif revise:
                    saved = order._vendor_propose_changes(
                        self._read_revision_edits(order, kw), (kw.get("revise_note") or "")[:500], access.partner_id)
                elif withdraw:
                    revision = order.sudo().hlv_revision_ids.filtered(lambda r: str(r.id) == str(withdraw))
                    if not revision:
                        raise UserError("Không tìm thấy yêu cầu.")
                    revision._vendor_withdraw(access.partner_id)
                    saved = "withdrawn"
                else:
                    order._vendor_set_status(status, access.partner_id)
            except UserError as exc:
                error = exc.args[0]
            else:
                if kw.get("next"):
                    # Cập nhật từ khung xem nhanh ở danh sách: về lại danh sách (chỉ trong link của NCC).
                    back_url = self._safe_next(access, kw["next"])
                    sep = "&" if "?" in back_url else "?"
                    return request.redirect(f"{back_url}{sep}{urlencode({'saved': order.name})}")
                back = f"&from={from_quote.id}" if from_quote else ""
                return request.redirect(f"{PORTAL_ROUTE}/{token}/{ORDERS}/{order.id}?saved={saved}{back}")
        return self._render("hlv_vendor_quotation.portal_order_form", access, {
            "order": order,
            "quotes": order.hlv_vendor_quote_ids,
            "info": self._order_info(order),
            "progress_labels": PROGRESS_LABELS,
            "saved": SAVED_MESSAGES.get(kw.get("saved") or "", ""),
            "ship_error": error,
            "post": request.params if error else {},
            "active_tab": "orders",
            "company": order.company_id,
            "chat": chat_messages(order, self._file_url(token)),
            "chat_key": f"order:{order.id}",
            "chat_doc": order.name,
            "from_quote": from_quote,
            "chat_url": f"{PORTAL_ROUTE}/{token}/{ORDERS}/{order.id}/tin-nhan",
            "chat_error": kw.get("chat_error") or "",
        })

    def _mark_shipped(self, order, access, form):
        """NCC báo đã gửi CPN / chành; ảnh vận đơn / phiếu gửi (nếu có) đăng vào trao đổi của đơn để
        bên mua xem cùng chỗ với tin nhắn."""
        order._vendor_mark_shipped(form.get("method"), form.get("carrier"), form.get("ref"), access.partner_id)
        files = self._uploaded_files()
        if files:
            post_chat(order, f"Ảnh vận đơn / phiếu gửi: {order.hlv_ship_carrier or ''} {order.hlv_ship_ref}".strip(),
                      access.partner_id, from_vendor=True, notify_partners=order._chat_contacts(), files=files)

    def _from_quote(self, access, quote_id):
        """Báo giá nguồn khi NCC đi từ báo giá sang đơn mua (?from=) — để breadcrumb quay lại.
        Chỉ nhận báo giá của chính NCC này; sai / thiếu → rỗng."""
        try:
            return self._get_quote(access, int(quote_id)) if quote_id else None
        except (TypeError, ValueError):
            return None

    @http.route(
        f"{PORTAL_ROUTE}/<string:token>/{ORDERS}/<int:order_id>/tin-nhan",
        type="http",
        auth="public",
        methods=["POST"],
    )
    def portal_order_chat(self, token, order_id, message="", **kw):
        """NCC nhắn cho bên mua trên một đơn mua."""
        access = self._get_access(token)
        if not access or not self._is_logged_in(access):
            return self._not_found()
        order = access._vendor_purchase_orders().filtered(lambda o: o.id == order_id)
        if not order:
            return self._not_found()
        from_quote = self._from_quote(access, kw.get("from"))
        return self._post_vendor_chat(
            order, access, message, order._chat_contacts(), f"{PORTAL_ROUTE}/{token}/{ORDERS}/{order.id}",
            {"from": from_quote.id} if from_quote else None,
        )

    @http.route(
        f"{PORTAL_ROUTE}/<string:token>/{ORDERS}/<int:order_id>/in",
        type="http",
        auth="public",
        methods=["GET"],
    )
    def portal_order_print(self, token, order_id, **kw):
        """Bản in đơn mua cho NCC: PDF mẫu "Đơn mua hàng" chuẩn (PRINT_REPORT), mở thẳng trên trình
        duyệt. Render bằng sudo — khách chưa đăng nhập Odoo không đọc được đơn mua."""
        access = self._get_access(token)
        if not access:
            return self._not_found()
        if not self._is_logged_in(access):
            return self._render_login(access, next_url=f"{PORTAL_ROUTE}/{token}/{ORDERS}/{order_id}/in")
        order = access._vendor_purchase_orders().filtered(lambda o: o.id == order_id)
        if not order:
            return self._not_found()
        pdf, _report_type = request.env["ir.actions.report"].sudo()._render_qweb_pdf(PRINT_REPORT, order.ids)
        return request.make_response(pdf, headers=[
            ("Content-Type", "application/pdf"),
            ("Content-Length", str(len(pdf))),
            ("Content-Disposition", f'inline; filename="{order.name.replace("/", "-")}.pdf"'),
        ])
