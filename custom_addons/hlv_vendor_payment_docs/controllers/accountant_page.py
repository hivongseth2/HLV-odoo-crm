# -*- coding: utf-8 -*-
"""Trang /unc-ncc của kế toán: tìm đề nghị chi của đơn mua, xem đủ thông tin, tải UNC / ảnh / PDF / Word lên, ẩn với
NCC hoặc xoá. Phần thanh toán công nợ (một khoản trả nhiều đơn) ở controllers/debt_payment_page.py. Chỉ nhóm "Kế toán: chứng từ chi NCC" vào được; đã kiểm nhóm thì đọc / ghi bằng sudo (giữ người dùng —
chứng từ vẫn ghi đúng người tải). Form thường, chạy không cần JS."""

from urllib.parse import urlencode

from markupsafe import Markup
from odoo import fields, http
from odoo.addons.hlv_vendor_quotation.models.purchase_order import CONFIRMED_STATES
from odoo.addons.hlv_vendor_quotation.models.purchase_order_revision import tax_rate_of
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import format_vn_number, local_date_text, paginate
from odoo.addons.hlv_vendor_quotation.services.asset_version import asset_version
from odoo.http import request

from ..models.payment_utils import ALLOWED_EXTENSIONS, MAX_DOCUMENT_BYTES, document_error

ROUTE = "/unc-ncc"
DEBT_ROUTE = f"{ROUTE}/cong-no"
GROUP = "hlv_vendor_payment_docs.group_payment_doc_accountant"
PER_PAGE = 30
SEARCH_MAX = 64
# Thông báo sau khi lưu (?saved=…).
SAVED_MESSAGES = {
    "uploaded": "Đã tải chứng từ lên — NCC thấy ngay trên tab Tài chính của link báo giá.",
    "hidden": "Đã ẩn chứng từ với NCC.",
    "shown": "Đã cho NCC xem chứng từ.",
    "deleted": "Đã xoá chứng từ.",
}


class AccountantPaymentPage(http.Controller):

    def _forbidden(self):
        return request.make_response("Bạn chưa có quyền \"Kế toán: chứng từ chi NCC\" — nhờ quản trị cấp quyền.",
                                     headers=[("Content-Type", "text/plain; charset=utf-8")], status=403)

    @staticmethod
    def _allowed():
        return request.env.user.has_group(GROUP)

    def _render(self, template, values):
        context = {
            "doctype": Markup("<!DOCTYPE html>"),
            "asset_version": asset_version(),
            "company": request.env.company.sudo(),
            "fmt": format_vn_number,
            "fdate": local_date_text,
            "route": ROUTE,
            "accept": ",".join(ALLOWED_EXTENSIONS),
            "max_mb": MAX_DOCUMENT_BYTES // (1024 * 1024),
            "debt_route": DEBT_ROUTE,
            "section": "requests",
        }
        context.update(values)
        return request.render(template, context)

    # ------------------------------------------------------------------ danh sách
    @http.route(ROUTE, type="http", auth="user", methods=["GET"])
    def payment_list(self, page=1, **kw):
        if not self._allowed():
            return self._forbidden()
        filters = self._read_filters(kw)
        Request = request.env["amis.payment.request"].sudo()
        domain = self._domain(filters)
        pager = paginate(Request.search_count(domain), page, PER_PAGE)
        requests = Request.search(domain, order="payment_date desc, id desc", offset=pager["offset"], limit=pager["limit"])
        return self._render("hlv_vendor_payment_docs.accountant_list", {
            "page_title": "Chứng từ chi NCC",
            "requests": requests,
            "filters": filters,
            "state_options": Request._fields["state"].selection,
            "pager": pager,
            "list_url": lambda **changes: self._list_url(filters, **changes),
        })

    @staticmethod
    def _read_filters(form):
        """Bộ lọc từ URL: chữ tìm (số đề nghị / số đơn mua / NCC), trạng thái MISA, có / chưa có chứng từ, khoảng ngày
        đề nghị chi (yyyy-mm-dd — sai thì bỏ qua)."""
        def day(key):
            try:
                return fields.Date.to_date((form.get(key) or "").strip()) or None
            except ValueError:
                return None

        return {
            "q": (form.get("q") or "").strip()[:SEARCH_MAX],
            "state": (form.get("state") or "").strip(),
            "docs": form.get("docs") if form.get("docs") in ("co", "chua") else "",
            "date_from": day("date_from"),
            "date_to": day("date_to"),
        }

    @staticmethod
    def _domain(filters):
        # Chỉ đề nghị chi của đơn mua — đề nghị chi đổi điểm (loyalty) không phải việc chứng từ NCC.
        domain = [("purchase_order_id", "!=", False)]
        if filters["q"]:
            q = filters["q"]
            domain += ["|", "|", ("name", "ilike", q), ("purchase_order_id.name", "ilike", q), ("partner_id.name", "ilike", q)]
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

    @staticmethod
    def _list_url(filters, base=ROUTE, **changes):
        """URL danh sách (base: đề nghị chi hoặc công nợ) giữ bộ lọc hiện tại, đổi những gì truyền vào changes."""
        params = {
            "q": filters["q"], "state": filters["state"], "docs": filters["docs"],
            "date_from": filters["date_from"].isoformat() if filters["date_from"] else "",
            "date_to": filters["date_to"].isoformat() if filters["date_to"] else "",
        }
        params.update(changes)
        if str(params.get("page", "")) == "1":
            params.pop("page")  # trang 1 là mặc định — URL gọn
        query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
        return f"{base}?{query}" if query else base

    # ------------------------------------------------------------------ một đề nghị chi
    def _payment_request(self, request_id):
        record = request.env["amis.payment.request"].sudo().browse(request_id).exists()
        return record if record and record.purchase_order_id else None

    @http.route(f"{ROUTE}/<int:request_id>", type="http", auth="user", methods=["GET"])
    def payment_detail(self, request_id, saved=None, error=None, **_kw):
        if not self._allowed():
            return self._forbidden()
        payment = self._payment_request(request_id)
        if not payment:
            return request.not_found()
        return self._render("hlv_vendor_payment_docs.accountant_detail", {
            "page_title": payment.name,
            "payment": payment,
            "saved": SAVED_MESSAGES.get(saved or "", ""),
            "error": (error or "")[:500],
        })

    @http.route(f"{ROUTE}/<int:request_id>/tai-len", type="http", auth="user", methods=["POST"])
    def payment_upload(self, request_id, note="", **_kw):
        if not self._allowed():
            return self._forbidden()
        payment = self._payment_request(request_id)
        if not payment:
            return request.not_found()
        return request.redirect(self._upload_documents(payment, note, f"{ROUTE}/{payment.id}"))

    @staticmethod
    def _read_uploads():
        """File trong ô "files" của form: ([(tên, bytes, mimetype)] nhận được, [lý do bỏ từng file])."""
        files, errors = [], []
        for upload in request.httprequest.files.getlist("files"):
            if not upload.filename:
                continue  # ô file để trống — form vẫn gửi một phần tử rỗng
            data = upload.read(MAX_DOCUMENT_BYTES + 1)
            error = document_error(upload.filename, len(data))
            if error:
                errors.append(error)
            else:
                files.append((upload.filename, data, upload.mimetype))
        return files, errors

    def _upload_documents(self, owner, note, detail_url, saved=None):
        """Lưu file tải lên vào owner (đề nghị chi / phiếu công nợ); trả URL quay về trang chi tiết kèm thông báo.
        saved: thông báo khi đã lưu việc khác (tạo phiếu) — có thì không chọn file cũng không phải lỗi."""
        files, errors = self._read_uploads()
        if not files and not errors and not saved:
            errors.append("Chưa chọn file nào.")
        if files:
            request.env["hlv.payment.document"].sudo()._create_for(owner, files, note)
        saved = saved or ("uploaded" if files else None)
        params = {"saved": saved} if saved else {}
        if errors:
            params["error"] = "; ".join(errors)
        return f"{detail_url}?{urlencode(params)}"

    @staticmethod
    def _owner_url(document):
        """Trang kế toán của đề nghị chi / phiếu công nợ chứa chứng từ."""
        if document.debt_payment_id:
            return f"{DEBT_ROUTE}/{document.debt_payment_id.id}"
        return f"{ROUTE}/{document.payment_request_id.id}"

    @http.route(f"{ROUTE}/chung-tu/<int:doc_id>", type="http", auth="user", methods=["POST"])
    def document_action(self, doc_id, action="", **_kw):
        """Ẩn / cho NCC xem / xoá một chứng từ."""
        if not self._allowed():
            return self._forbidden()
        document = request.env["hlv.payment.document"].sudo().browse(doc_id).exists()
        if not document:
            return request.not_found()
        owner_url = self._owner_url(document)
        if action == "delete":
            document.unlink()
            saved = "deleted"
        else:
            document.visible_to_vendor = not document.visible_to_vendor
            saved = "shown" if document.visible_to_vendor else "hidden"
        return request.redirect(f"{owner_url}?saved={saved}")

    @http.route(f"{ROUTE}/don-mua/<int:order_id>", type="http", auth="user", methods=["GET"])
    def order_view(self, order_id, **_kw):
        """Xem đơn mua (chỉ đọc) — kế toán đối chiếu hàng / tiền mà không cần quyền Mua hàng. Chỉ đơn có đề nghị chi, đã
        nhận tiền công nợ, hoặc đã xác nhận (để chọn đơn khi trả công nợ) — đơn nháp / báo giá không mở ở đây."""
        if not self._allowed():
            return self._forbidden()
        order = request.env["purchase.order"].sudo().browse(order_id).exists()
        if not order or not (order.misa_payment_request_ids or order.hlv_debt_line_ids
                             or order.state in CONFIRMED_STATES):
            return request.not_found()
        return self._render("hlv_vendor_payment_docs.accountant_order", {
            "page_title": order.name,
            "order": order,
            "lines": order.order_line.filtered(lambda l: not l.display_type),
            "tax_rate_of": tax_rate_of,
            "state_label": dict(order._fields["state"].selection).get(order.state, order.state),
        })

    @http.route(f"{ROUTE}/chung-tu/<int:doc_id>/xem", type="http", auth="user", methods=["GET"])
    def document_view(self, doc_id, **_kw):
        if not self._allowed():
            return self._forbidden()
        document = request.env["hlv.payment.document"].sudo().browse(doc_id).exists()
        if not document:
            return request.not_found()
        return request.env["ir.binary"]._get_stream_from(document.attachment_id, "raw").get_response(as_attachment=False)
