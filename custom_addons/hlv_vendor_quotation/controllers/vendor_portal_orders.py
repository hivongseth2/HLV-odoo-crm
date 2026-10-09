# -*- coding: utf-8 -*-
"""Tab "Đơn mua hàng" trên link của NCC: đơn mua sinh ra từ báo giá của NCC, chia tab theo tiến độ
(đã nhận chờ đóng / đã đóng gói / đã giao), và NCC báo tiến độ:
- "Đã đóng gói": NCC bấm;
- "Đã gửi hàng": chỉ đơn gửi CPN / gửi chành — NCC nhập mã vận đơn hoặc tên chành + số xe;
- "Đã giao": tự chuyển khi kho bên mua nhận đủ hàng — NCC không phải bấm.

Kế thừa VendorQuotePortal (cơ chế mở rộng controller của Odoo) để dùng chung đăng nhập,
khung trang và các hàm phụ — không chép lại.
"""

from urllib.parse import urlencode

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..models.purchase_order import PROGRESS_LABELS
from ..models.vendor_quote_access import PORTAL_ROUTE
from ..models.vendor_quote_utils import DELIVERY_CHANH, DELIVERY_CPN
from ..services.chat_read import mark_seen
from ..services.vendor_chat import chat_messages, post_chat
from ..services.vendor_feed import row_marks
from .vendor_portal import VendorQuotePortal

ORDERS = "don-mua"
# Tab danh sách đơn mua — khoá trùng PurchaseOrder._hlv_vendor_stage().
ORDER_TABS = [
    ("waiting", "Chờ đóng gói"),
    ("packed", "Đã đóng gói"),
    ("delivered", "Đã giao"),
    ("cancel", "Đã hủy"),
    ("all", "Tất cả"),
]
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
            # Mở tab chưa chọn: ưu tiên đơn đang chờ NCC đóng gói — việc NCC cần làm.
            stage = "waiting" if counts["waiting"] else "all"
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
            ],
            "order_quotes": {order.id: order.hlv_vendor_quote_ids for order in shown},
            "marks": row_marks(shown, access),
            "progress_labels": PROGRESS_LABELS,
            "post": {},
            "active_tab": "orders",
        })

    @staticmethod
    def _order_info(order):
        """Thông tin một đơn cho trang NCC: tiến độ, phương thức / địa điểm giao hàng, cách giao đoán từ
        phương thức (CPN / chành → mặc định chọn "Gửi CPN / chành" khi NCC báo đã gửi)."""
        mode = order._hlv_delivery_mode()
        return {
            "progress": order._hlv_vendor_progress(),
            "delivery_term": order._hlv_delivery_term(),
            "delivery_place": order._hlv_delivery_place(),
            "ship_mode": mode if mode in (DELIVERY_CPN, DELIVERY_CHANH) else "",
            "ship_text": order._hlv_ship_text(),
        }

    @http.route(
        f"{PORTAL_ROUTE}/<string:token>/{ORDERS}/<int:order_id>",
        type="http",
        auth="public",
        methods=["GET", "POST"],
    )
    def portal_order(self, token, order_id, status=None, ship=None, **kw):
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
        mark_seen([order], access)
        error = ""
        if request.httprequest.method == "POST" and (status or ship):
            try:
                if ship:
                    self._mark_shipped(order, access, kw)
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
                return request.redirect(f"{PORTAL_ROUTE}/{token}/{ORDERS}/{order.id}?saved=1{back}")
        return self._render("hlv_vendor_quotation.portal_order_form", access, {
            "order": order,
            "quotes": order.hlv_vendor_quote_ids,
            "info": self._order_info(order),
            "progress_labels": PROGRESS_LABELS,
            "saved": bool(kw.get("saved")),
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
