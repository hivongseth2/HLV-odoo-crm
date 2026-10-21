# -*- coding: utf-8 -*-
"""Tab "Tất cả" của trang /unc-ncc: đề nghị chi đơn mua và phiếu thanh toán công nợ chung một danh sách, mới trước —
kế toán tìm một khoản chi mà không cần biết nó đi đường nào. Lọc / tìm dùng lại domain của hai tab riêng."""

from odoo import http
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import paginate
from odoo.http import request

from .accountant_page import ALL_ROUTE, PER_PAGE
from .debt_payment_page import DebtPaymentPage

KINDS = ("dnc", "cong-no")


class AllPaymentsPage(DebtPaymentPage):

    @http.route(ALL_ROUTE, type="http", auth="user", methods=["GET"])
    def all_list(self, page=1, **kw):
        if not self._allowed():
            return self._forbidden()
        filters = dict(self._read_filters(kw), state="")  # trạng thái hai loại khác nhau — tab này không lọc
        kind = kw.get("loai") if kw.get("loai") in KINDS else ""
        Request = request.env["amis.payment.request"].sudo()
        Debt = request.env["hlv.vendor.debt.payment"].sudo()
        request_domain = self._domain(filters) if kind != "cong-no" else [("id", "=", 0)]
        debt_domain = self._debt_domain(filters) if kind != "dnc" else [("id", "=", 0)]
        total = Request.search_count(request_domain) + Debt.search_count(debt_domain)
        pager = paginate(total, page, PER_PAGE)
        # Trang thứ n của danh sách trộn nằm trong (offset + limit) bản ghi mới nhất của MỖI loại — lấy chừng đó rồi
        # trộn, khỏi đọc hết hai bảng.
        top = pager["offset"] + pager["limit"]
        order = "payment_date desc, create_date desc"
        entries = sorted([*Request.search(request_domain, order=order, limit=top),
                          *Debt.search(debt_domain, order=order, limit=top)],
                         key=lambda r: (r.payment_date, r.create_date), reverse=True)
        return self._render("hlv_vendor_payment_docs.accountant_all_list", {
            "page_title": "Tất cả khoản chi NCC",
            "section": "all",
            "entries": entries[pager["offset"]:top],
            "filters": filters,
            "kind": kind,
            "pager": pager,
            "list_url": lambda **changes: self._list_url(filters, base=ALL_ROUTE, loai=kind, **changes),
            "entry_url": self._entry_url,
        })

