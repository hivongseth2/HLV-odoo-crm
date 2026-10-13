# -*- coding: utf-8 -*-
"""Tab "Tài chính" trên link báo giá của NCC: đã chi / đang xử lý / còn lại, các đề nghị chi của đơn mua của NCC kèm
chứng từ kế toán tải lên. Lọc theo số đề nghị / số đơn, trạng thái, có chứng từ, khoảng ngày, một đơn mua; phân trang —
form GET, chạy không cần JS. Kế thừa VendorQuotePortal để dùng chung đăng nhập, khung trang, tab."""

from urllib.parse import urlencode

from odoo import fields, http
from odoo.addons.hlv_vendor_quotation.controllers.vendor_portal import VendorQuotePortal
from odoo.addons.hlv_vendor_quotation.models.purchase_order import CONFIRMED_STATES
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_access import PORTAL_ROUTE
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import paginate
from odoo.http import request

from ..models.payment_request import VENDOR_PAYMENT_STATES

FINANCE = "tai-chinh"
PER_PAGE = 30
SEARCH_MAX = 64
PAID_STATES_FILTER = {"da-chi": True, "dang-xu-ly": False}


class VendorFinancePortal(VendorQuotePortal):

    def _finance_access(self, token):
        """(access, response): response khác None là trang cần trả ngay (không có link / chưa đăng nhập)."""
        access = self._get_access(token)
        if not access:
            return None, self._not_found()
        if not self._is_logged_in(access):
            return None, self._render_login(access, next_url=f"{PORTAL_ROUTE}/{token}/{FINANCE}")
        return access, None

    @http.route(f"{PORTAL_ROUTE}/<string:token>/{FINANCE}", type="http", auth="public", methods=["GET"])
    def portal_finance(self, token, page=1, **kw):
        access, response = self._finance_access(token)
        if response:
            return response
        orders = access._vendor_purchase_orders()
        all_requests = request.env["amis.payment.request"].sudo().search(
            [("purchase_order_id", "in", orders.ids), ("state", "in", VENDOR_PAYMENT_STATES)],
            order="payment_date desc, id desc")
        filters = self._read_filters(kw, orders)
        shown = all_requests.filtered(lambda r: self._match(r, filters))
        pager = paginate(len(shown), page, PER_PAGE)
        paid = sum(r.amount for r in all_requests if r._hlv_is_paid())
        confirmed_total = sum(orders.filtered(lambda o: o.state in CONFIRMED_STATES).mapped("amount_total"))
        return self._render("hlv_vendor_payment_docs.portal_finance", access, {
            "active_tab": "finance",
            "requests": shown[pager["offset"]:pager["offset"] + pager["limit"]],
            "result_count": len(shown),
            "filters": filters,
            "order_options": all_requests.purchase_order_id.sorted("name", reverse=True),
            "kpi": {
                "paid": paid,
                "processing": sum(r.amount for r in all_requests if not r._hlv_is_paid()),
                "orders_total": confirmed_total,
                "remaining": max(confirmed_total - paid, 0.0),
            },
            "pager": pager,
            "finance_url": lambda **changes: self._finance_url(access, filters, **changes),
            "doc_url": lambda doc: f"{access._portal_path()}/{FINANCE}/chung-tu/{doc.id}",
        })

    def _vendor_payment(self, access, request_id):
        """Đề nghị chi NCC được xem: của đơn mua của chính NCC, trạng thái NCC được thấy. Không có → None."""
        payment = request.env["amis.payment.request"].sudo().browse(request_id).exists()
        if (not payment or payment.state not in VENDOR_PAYMENT_STATES
                or payment.purchase_order_id not in access._vendor_purchase_orders()):
            return None
        return payment

    @http.route(f"{PORTAL_ROUTE}/<string:token>/{FINANCE}/<int:request_id>", type="http", auth="public", methods=["GET"])
    def portal_finance_detail(self, token, request_id, doc=None, **_kw):
        """Một đề nghị chi: thông tin + chứng từ kế toán gửi, xem lớn ngay trong trang (?doc= chọn chứng từ đang xem)."""
        access, response = self._finance_access(token)
        if response:
            return response
        payment = self._vendor_payment(access, request_id)
        if not payment:
            return self._not_found()
        documents = payment._hlv_vendor_documents()
        current = documents.filtered(lambda d: str(d.id) == str(doc))[:1] or documents[:1]
        return self._render("hlv_vendor_payment_docs.portal_finance_detail", access, {
            "active_tab": "finance",
            "payment": payment,
            "documents": documents,
            "current": current,
            "doc_url": lambda document: f"{access._portal_path()}/{FINANCE}/chung-tu/{document.id}",
            "detail_url": f"{access._portal_path()}/{FINANCE}/{payment.id}",
        })

    @staticmethod
    def _read_filters(form, orders):
        """Bộ lọc từ URL: chữ (số đề nghị / số đơn), trạng thái (da-chi / dang-xu-ly), chứng từ (co / chua), khoảng ngày
        đề nghị chi, một đơn mua (chỉ đơn của chính NCC — id lạ bỏ qua)."""
        def day(key):
            try:
                return fields.Date.to_date((form.get(key) or "").strip()) or None
            except ValueError:
                return None

        try:
            order_id = int(form.get("order") or 0)
        except (TypeError, ValueError):
            order_id = 0
        return {
            "q": (form.get("q") or "").strip()[:SEARCH_MAX],
            "status": form.get("status") if form.get("status") in PAID_STATES_FILTER else "",
            "docs": form.get("docs") if form.get("docs") in ("co", "chua") else "",
            "date_from": day("date_from"),
            "date_to": day("date_to"),
            "order": order_id if order_id in orders.ids else 0,
        }

    @staticmethod
    def _match(payment, filters):
        """Đề nghị chi khớp bộ lọc không (lọc trên tập đã giới hạn theo NCC — không đủ lớn để cần domain)."""
        q = filters["q"].lower()
        if q and q not in (payment.name or "").lower() and q not in (payment.purchase_order_id.name or "").lower():
            return False
        if filters["status"] and payment._hlv_is_paid() != PAID_STATES_FILTER[filters["status"]]:
            return False
        documents = payment._hlv_vendor_documents()
        if (filters["docs"] == "co" and not documents) or (filters["docs"] == "chua" and documents):
            return False
        if filters["date_from"] and payment.payment_date < filters["date_from"]:
            return False
        if filters["date_to"] and payment.payment_date > filters["date_to"]:
            return False
        return not filters["order"] or payment.purchase_order_id.id == filters["order"]

    @staticmethod
    def _finance_url(access, filters, **changes):
        params = {
            "q": filters["q"], "status": filters["status"], "docs": filters["docs"],
            "date_from": filters["date_from"].isoformat() if filters["date_from"] else "",
            "date_to": filters["date_to"].isoformat() if filters["date_to"] else "",
            "order": filters["order"] or "",
        }
        params.update(changes)
        if str(params.get("page", "")) == "1":
            params.pop("page")
        query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
        base = f"{access._portal_path()}/{FINANCE}"
        return f"{base}?{query}" if query else base

    @http.route(f"{PORTAL_ROUTE}/<string:token>/{FINANCE}/chung-tu/<int:doc_id>", type="http", auth="public",
                methods=["GET"])
    def portal_finance_document(self, token, doc_id, **_kw):
        """Mở chứng từ chi — chỉ của đơn mua của chính NCC này, đề nghị chi NCC được thấy, kế toán không ẩn."""
        access, response = self._finance_access(token)
        if response:
            return response
        document = request.env["hlv.payment.document"].sudo().browse(doc_id).exists()
        if (not document or not document.visible_to_vendor
                or not self._vendor_payment(access, document.payment_request_id.id)):
            return self._not_found()
        return request.env["ir.binary"]._get_stream_from(document.attachment_id, "raw").get_response(as_attachment=False)
