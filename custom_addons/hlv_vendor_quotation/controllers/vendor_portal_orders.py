# -*- coding: utf-8 -*-
"""Tab "Đơn mua hàng" trên link của NCC: đơn mua sinh ra từ báo giá của NCC, và NCC tự báo
tiến độ (đã đóng gói / đã giao).

Kế thừa VendorQuotePortal (cơ chế mở rộng controller của Odoo) để dùng chung đăng nhập,
khung trang và các hàm phụ — không chép lại.
"""

from odoo import http
from odoo.http import request

from ..models.purchase_order import VENDOR_STATUS
from ..models.vendor_quote_access import PORTAL_ROUTE
from ..services.vendor_chat import chat_messages, post_chat
from .vendor_portal import VendorQuotePortal

ORDERS = "don-mua"


class VendorPurchaseOrderPortal(VendorQuotePortal):

    @http.route(f"{PORTAL_ROUTE}/<string:token>/{ORDERS}", type="http", auth="public", methods=["GET"])
    def portal_orders(self, token, **kw):
        access = self._get_access(token)
        if not access:
            return self._not_found()
        if not self._is_logged_in(access):
            return self._render_login(access, next_url=f"{PORTAL_ROUTE}/{token}/{ORDERS}")
        orders = access._vendor_purchase_orders().sorted(lambda o: o.date_order, reverse=True)
        return self._render("hlv_vendor_quotation.portal_order_list", access, {
            "orders": orders,
            "order_quotes": {order.id: order.hlv_vendor_quote_ids for order in orders},
            "vendor_status_labels": dict(VENDOR_STATUS),
            "active_tab": "orders",
        })

    @http.route(
        f"{PORTAL_ROUTE}/<string:token>/{ORDERS}/<int:order_id>",
        type="http",
        auth="public",
        methods=["GET", "POST"],
    )
    def portal_order(self, token, order_id, status=None, **kw):
        access = self._get_access(token)
        if not access:
            return self._not_found()
        if not self._is_logged_in(access):
            return self._render_login(access, next_url=f"{PORTAL_ROUTE}/{token}/{ORDERS}/{order_id}")
        # Chỉ đơn mua sinh ra từ báo giá của chính NCC này — không mở đơn khác bằng id.
        order = access._vendor_purchase_orders().filtered(lambda o: o.id == order_id)
        if not order:
            return self._not_found()
        if request.httprequest.method == "POST" and status:
            order._vendor_set_status(status, access.partner_id)
            return request.redirect(f"{PORTAL_ROUTE}/{token}/{ORDERS}/{order.id}?saved=1")
        return self._render("hlv_vendor_quotation.portal_order_form", access, {
            "order": order,
            "quotes": order.hlv_vendor_quote_ids,
            "vendor_status": VENDOR_STATUS,
            "vendor_status_labels": dict(VENDOR_STATUS),
            "saved": bool(kw.get("saved")),
            "active_tab": "orders",
            "company": order.company_id,
            "chat": chat_messages(order),
            "chat_url": f"{PORTAL_ROUTE}/{token}/{ORDERS}/{order.id}/tin-nhan",
        })

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
        if (message or "").strip():
            post_chat(order, message, access.partner_id, from_vendor=True, notify_partners=order._chat_contacts())
        return request.redirect(f"{PORTAL_ROUTE}/{token}/{ORDERS}/{order.id}#trao-doi")
