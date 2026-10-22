# -*- coding: utf-8 -*-
"""Tab "Tài chính" trên link báo giá của NCC: đã chi / đang xử lý / còn lại, các đề nghị chi của đơn mua của NCC và các
phiếu thanh toán công nợ (một khoản trả nhiều đơn) kèm chứng từ kế toán tải lên. Lọc theo số đề nghị / số đơn, trạng thái, có chứng từ, khoảng ngày, một đơn mua; phân trang —
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
DEBT = "cong-no"
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
        all_requests, debts = access._hlv_finance_records(orders)
        # Hai loại phiếu chung một danh sách — cùng các hàm _hlv_is_paid / _hlv_orders / _hlv_vendor_documents.
        entries = sorted([*all_requests, *debts], key=lambda r: (r.payment_date, r.create_date), reverse=True)
        filters = self._read_filters(kw, orders)
        shown = [entry for entry in entries if self._match(entry, filters)]
        pager = paginate(len(shown), page, PER_PAGE)
        # Đơn được phiếu công nợ trả đã nằm trong tab "Đơn mua hàng" (vendor_quote_access.py) — trừ khi trạng thái của
        # nó không thuộc trạng thái NCC được thấy (Cài đặt). Vẫn tính vào "giá trị đơn" để "đã chi" cộng đủ tiền phiếu
        # mà "còn lại" không bị trừ oan.
        kpi_orders = (orders | debts.line_ids.purchase_order_id).filtered(lambda o: o.state in CONFIRMED_STATES)
        paid = (sum(r.amount for r in all_requests if r._hlv_is_paid()) + sum(debts.mapped("amount")))
        confirmed_total = sum(kpi_orders.mapped("amount_total"))
        return self._render("hlv_vendor_payment_docs.portal_finance", access, {
            "active_tab": "finance",
            "requests": shown[pager["offset"]:pager["offset"] + pager["limit"]],
            "result_count": len(shown),
            "filters": filters,
            "order_options": ((all_requests.purchase_order_id | debts.line_ids.purchase_order_id) & orders).sorted(
                "name", reverse=True),
            "visible_orders": orders,
            "kpi": {
                "paid": paid,
                "processing": sum(r.amount for r in all_requests if not r._hlv_is_paid()),
                "orders_total": confirmed_total,
                "remaining": max(confirmed_total - paid, 0.0),
            },
            "pager": pager,
            "finance_url": lambda **changes: self._finance_url(access, filters, **changes),
            "doc_url": lambda doc: f"{access._portal_path()}/{FINANCE}/chung-tu/{doc.id}",
            "entry_url": lambda entry: self._entry_url(access, entry),
        })

    @staticmethod
    def _entry_url(access, entry):
        """Trang NCC của một đề nghị chi / phiếu công nợ."""
        if entry._name == "hlv.vendor.debt.payment":
            return f"{access._portal_path()}/{FINANCE}/{DEBT}/{entry.id}"
        return f"{access._portal_path()}/{FINANCE}/{entry.id}"

    def _vendor_debt(self, access, payment_id):
        """Phiếu công nợ NCC được xem: của chính NCC, còn hiệu lực. Không có → None."""
        payment = request.env["hlv.vendor.debt.payment"].sudo().browse(payment_id).exists()
        if (not payment or payment.state != "done"
                or payment.partner_id != access.partner_id.commercial_partner_id):
            return None
        return payment

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

    @http.route(f"{PORTAL_ROUTE}/<string:token>/{FINANCE}/{DEBT}/<int:payment_id>", type="http", auth="public",
                methods=["GET"])
    def portal_finance_debt_detail(self, token, payment_id, doc=None, **_kw):
        """Một phiếu thanh toán công nợ: số tiền, các đơn được trả, chứng từ kế toán gửi (xem lớn như đề nghị chi)."""
        access, response = self._finance_access(token)
        if response:
            return response
        payment = self._vendor_debt(access, payment_id)
        if not payment:
            return self._not_found()
        documents = payment._hlv_vendor_documents()
        return self._render("hlv_vendor_payment_docs.portal_finance_debt_detail", access, {
            "active_tab": "finance",
            "payment": payment,
            "visible_orders": access._vendor_purchase_orders(),
            "documents": documents,
            "current": documents.filtered(lambda d: str(d.id) == str(doc))[:1] or documents[:1],
            "doc_url": lambda document: f"{access._portal_path()}/{FINANCE}/chung-tu/{document.id}",
            "detail_url": self._entry_url(access, payment),
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
        """Đề nghị chi / phiếu công nợ khớp bộ lọc không (lọc trên tập đã giới hạn theo NCC — không đủ lớn để cần
        domain)."""
        q = filters["q"].lower()
        names = [payment.name or "", *payment._hlv_orders().mapped("name")]
        if q and not any(q in name.lower() for name in names):
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
        return not filters["order"] or filters["order"] in payment._hlv_orders().ids

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
        """Mở chứng từ chi — chỉ của đề nghị chi / phiếu công nợ NCC này được thấy, kế toán không ẩn."""
        access, response = self._finance_access(token)
        if response:
            return response
        document = request.env["hlv.payment.document"].sudo().browse(doc_id).exists()
        if not document or not document.visible_to_vendor:
            return self._not_found()
        if document.debt_payment_id:
            owner = self._vendor_debt(access, document.debt_payment_id.id)
        else:
            owner = self._vendor_payment(access, document.payment_request_id.id)
        if not owner:
            return self._not_found()
        return request.env["ir.binary"]._get_stream_from(document.attachment_id, "raw").get_response(as_attachment=False)
