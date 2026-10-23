# -*- coding: utf-8 -*-
"""Trang /unc-ncc/cong-no của kế toán: ghi nhận một lần trả công nợ cho NCC — một khoản tiền trả nhiều đơn mua, kế
toán đã làm trên MISA (Odoo không đẩy đi đâu). Tạo: chọn NCC → tick các đơn còn nợ, sửa số trả vào từng đơn → lưu kèm
UNC. Trả một phần đơn / còn dư / đơn đang có đề nghị chi chờ duyệt thì phải xác nhận cảnh báo mới lưu. Kế thừa trang đề
nghị chi để dùng chung quyền, khung trang, tải file."""

from odoo import Command, fields, http
from odoo.addons.hlv_vendor_quotation.models.purchase_order import CONFIRMED_STATES
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import format_vn_number, paginate, parse_vn_number
from odoo.http import request

from ..models.payment_utils import debt_allocation_issues
from .accountant_page import DEBT_ROUTE, PER_PAGE, SAVED_MESSAGES, AccountantPaymentPage

SUPPLIER_LIMIT = 30
MEMO_MAX = 2000
DEBT_SAVED_MESSAGES = dict(SAVED_MESSAGES, **{
    "created": "Đã ghi nhận thanh toán công nợ — các đơn được trả cập nhật đã chi, NCC thấy ngay trên tab Tài chính.",
    "cancelled": "Đã huỷ phiếu — số tiền không còn tính vào đã chi của các đơn.",
})
DEBT_STATES = ("done", "cancelled")


class DebtPaymentPage(AccountantPaymentPage):

    def _render_debt(self, template, values):
        return self._render(template, dict(values, section="debt"))

    # ------------------------------------------------------------------ danh sách
    @http.route(DEBT_ROUTE, type="http", auth="user", methods=["GET"])
    def debt_list(self, page=1, **kw):
        if not self._allowed():
            return self._forbidden()
        filters = self._read_filters(kw)
        if filters["state"] not in DEBT_STATES:
            filters["state"] = ""
        Debt = request.env["hlv.vendor.debt.payment"].sudo()
        domain = self._debt_domain(filters)
        pager = paginate(Debt.search_count(domain), page, PER_PAGE)
        return self._render_debt("hlv_vendor_payment_docs.accountant_debt_list", {
            "page_title": "Thanh toán công nợ NCC",
            "payments": Debt.search(domain, offset=pager["offset"], limit=pager["limit"]),
            "filters": filters,
            "state_options": Debt._fields["state"].selection,
            "pager": pager,
            "list_url": lambda **changes: self._list_url(filters, base=DEBT_ROUTE, **changes),
        })

    @staticmethod
    def _debt_domain(filters):
        domain = []
        if filters["q"]:
            q = filters["q"]
            domain += ["|", "|", ("name", "ilike", q), ("partner_id.name", "ilike", q),
                       ("line_ids.purchase_order_id.name", "ilike", q)]
        if filters["state"]:
            domain.append(("state", "=", filters["state"]))
        if filters["docs"] == "co":
            domain.append(("hlv_document_ids", "!=", False))
        elif filters["docs"] == "chua":
            domain.append(("hlv_document_ids", "=", False))
        if filters["date_from"]:
            domain.append(("payment_date", ">=", filters["date_from"]))
        if filters["date_to"]:
            domain.append(("payment_date", "<=", filters["date_to"]))
        return domain

    # ------------------------------------------------------------------ tạo phiếu
    @staticmethod
    def _vendor(partner_id):
        """NCC (pháp nhân) theo id trên URL / form; id lạ → None."""
        try:
            partner = request.env["res.partner"].sudo().browse(int(partner_id or 0)).exists()
        except (TypeError, ValueError):
            return None
        return partner.commercial_partner_id or None

    @staticmethod
    def _find_vendors(text):
        """NCC trả công nợ được: có mã số thuế, VÀ có đơn mua đã xác nhận hoặc supplier_rank > 1 (đã mua nhiều lần —
        loại liên hệ chỉ lỡ tạo một đơn nháp). Khớp chữ tìm (tên / MST / mã) — tối đa SUPPLIER_LIMIT, theo tên."""
        groups = request.env["purchase.order"].sudo()._read_group(
            [("state", "in", CONFIRMED_STATES)], ["partner_id"], ["__count"])
        ordered_ids = list({partner.commercial_partner_id.id for partner, _count in groups})
        domain = [("vat", "!=", False), ("vat", "!=", ""),
                  "|", ("supplier_rank", ">", 1), ("id", "in", ordered_ids)]
        if text:
            domain += ["|", "|", ("name", "ilike", text), ("vat", "ilike", text), ("ref", "ilike", text)]
        return request.env["res.partner"].sudo().search(domain, order="name", limit=SUPPLIER_LIMIT)

    @http.route(f"{DEBT_ROUTE}/moi", type="http", auth="user", methods=["GET"])
    def debt_new(self, partner=None, ncc="", **_kw):
        if not self._allowed():
            return self._forbidden()
        vendor = self._vendor(partner)
        if not vendor:
            ncc = (ncc or "").strip()[:64]
            return self._render_debt("hlv_vendor_payment_docs.accountant_debt_pick_vendor", {
                "page_title": "Trả công nợ NCC",
                "ncc": ncc,
                "vendors": self._find_vendors(ncc),
            })
        return self._render_new(vendor, self._empty_entry())

    @staticmethod
    def _empty_entry():
        return {"amount_text": "", "payment_date": fields.Date.context_today(request.env.user),
                "payment_method": "bank", "memo": "", "note": "", "selected": set(), "alloc": {}, "rows": []}

    def _render_new(self, vendor, entry, errors=(), warnings=(), files_dropped=False):
        orders = request.env["purchase.order"]._hlv_open_orders_of(vendor)
        return self._render_debt("hlv_vendor_payment_docs.accountant_debt_new", {
            "page_title": "Trả công nợ " + vendor.name,
            "vendor": vendor,
            "orders": [{"order": order, "paid": order._hlv_paid_amount(), "open": order._hlv_open_amount(),
                        "processing": order._hlv_processing_amount()} for order in orders],
            "entry": entry,
            "errors": list(errors),
            "warnings": list(warnings),
            "files_dropped": files_dropped,
        })

    @staticmethod
    def _read_entry(form, vendor):
        """Phiếu kế toán nhập trên form: số tiền, ngày, hình thức, diễn giải, đơn được tick + số trả vào từng đơn. Giữ
        nguyên chữ đã gõ để vẽ lại form khi có lỗi / cảnh báo."""
        try:
            payment_date = fields.Date.to_date((form.get("payment_date") or "").strip()) or None
        except ValueError:
            payment_date = None
        selected = {int(value) for value in request.httprequest.form.getlist("order_ids") if value.isdigit()}
        orders = request.env["purchase.order"].sudo().search(
            [("id", "in", list(selected)), ("partner_id", "child_of", vendor.id), ("state", "in", CONFIRMED_STATES)],
            order="date_approve asc, id asc")
        alloc = {order.id: (form.get(f"alloc_{order.id}") or "").strip()[:32] for order in orders}
        return {
            "amount_text": (form.get("amount") or "").strip()[:32],
            "amount": parse_vn_number(form.get("amount")),
            "payment_date": payment_date or fields.Date.context_today(request.env.user),
            "payment_method": form.get("payment_method") if form.get("payment_method") in ("bank", "cash") else "bank",
            "memo": (form.get("memo") or "").strip()[:MEMO_MAX],
            "note": (form.get("note") or "").strip()[:255],
            "selected": set(orders.ids),
            "alloc": alloc,
            "rows": [{"order": order, "name": order.name, "open": order._hlv_open_amount(),
                      "allocated": parse_vn_number(alloc[order.id]), "processing": order._hlv_processing_amount()}
                     for order in orders],
        }

    @http.route(f"{DEBT_ROUTE}/kiem-tra", type="http", auth="user", methods=["POST"])
    def debt_check(self, partner=None, **form):
        """Lỗi / cảnh báo của phiếu đang nhập (JSON) — trang hỏi xác nhận trước khi gửi, khỏi chọn lại file."""
        if not self._allowed():
            return self._forbidden()
        vendor = self._vendor(partner)
        if not vendor:
            return request.not_found()
        entry = self._read_entry(form, vendor)
        errors, warnings = debt_allocation_issues(entry["amount"], entry["rows"])
        return request.make_json_response({"errors": errors, "warnings": warnings})

    @http.route(f"{DEBT_ROUTE}/moi", type="http", auth="user", methods=["POST"])
    def debt_create(self, partner=None, confirmed=None, **form):
        if not self._allowed():
            return self._forbidden()
        vendor = self._vendor(partner)
        if not vendor:
            return request.not_found()
        entry = self._read_entry(form, vendor)
        errors, warnings = debt_allocation_issues(entry["amount"], entry["rows"])
        if errors or (warnings and confirmed != "1"):
            # Chạy không JS (hoặc JS chưa kịp hỏi): vẽ lại form kèm lỗi / cảnh báo; file trình duyệt không giữ lại.
            files_dropped = any(upload.filename for upload in request.httprequest.files.getlist("files"))
            return self._render_new(vendor, entry, errors, warnings, files_dropped)
        payment = request.env["hlv.vendor.debt.payment"].sudo().create({
            "partner_id": vendor.id,
            "amount": entry["amount"],
            "payment_date": entry["payment_date"],
            "payment_method": entry["payment_method"],
            "memo": entry["memo"] or self._default_memo(entry["rows"]),
            "line_ids": [Command.create({"purchase_order_id": row["order"].id, "amount": row["allocated"]})
                         for row in entry["rows"]],
        })
        return request.redirect(self._upload_documents(payment, entry["note"], f"{DEBT_ROUTE}/{payment.id}",
                                                       saved="created"))

    @staticmethod
    def _default_memo(rows):
        """Diễn giải khi kế toán để trống: "Trả công nợ đơn PO1 (1.000.000), PO2 (…)"."""
        return "Trả công nợ đơn " + ", ".join(
            f"{row['name']} ({format_vn_number(round(row['allocated']))})" for row in rows)

    # ------------------------------------------------------------------ một phiếu
    def _debt_payment(self, payment_id):
        return request.env["hlv.vendor.debt.payment"].sudo().browse(payment_id).exists() or None

    @http.route(f"{DEBT_ROUTE}/<int:payment_id>", type="http", auth="user", methods=["GET"])
    def debt_detail(self, payment_id, saved=None, error=None, **_kw):
        if not self._allowed():
            return self._forbidden()
        payment = self._debt_payment(payment_id)
        if not payment:
            return request.not_found()
        return self._render_debt("hlv_vendor_payment_docs.accountant_debt_detail", {
            "page_title": payment.name,
            "payment": payment,
            "saved": DEBT_SAVED_MESSAGES.get(saved or "", ""),
            "error": (error or "")[:500],
        })

    @http.route(f"{DEBT_ROUTE}/<int:payment_id>/tai-len", type="http", auth="user", methods=["POST"])
    def debt_upload(self, payment_id, note="", **_kw):
        if not self._allowed():
            return self._forbidden()
        payment = self._debt_payment(payment_id)
        if not payment:
            return request.not_found()
        return request.redirect(self._upload_documents(payment, note, f"{DEBT_ROUTE}/{payment.id}"))

    @http.route(f"{DEBT_ROUTE}/<int:payment_id>/huy", type="http", auth="user", methods=["POST"])
    def debt_cancel(self, payment_id, **_kw):
        if not self._allowed():
            return self._forbidden()
        payment = self._debt_payment(payment_id)
        if not payment:
            return request.not_found()
        payment.action_cancel()
        return request.redirect(f"{DEBT_ROUTE}/{payment.id}?saved=cancelled")
