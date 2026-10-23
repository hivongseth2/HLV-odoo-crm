# -*- coding: utf-8 -*-
"""Trang /unc-ncc/cong-no/misa: lấy hoá đơn mua vào ĐÃ THANH TOÁN trên MISA thành phiếu thanh toán công nợ — kế toán
không lập tay từng phiếu. Không cron: người dùng bấm.
- Kế toán: chọn NCC rồi bấm lấy.
- Admin (base.group_system) thêm khung quản trị: mốc công nợ (đơn xác nhận trước mốc coi như đã chi xong —
  purchase_order.py) và lượt lấy cho mọi NCC có tài khoản vendor — mỗi lần bấm chạy tới khi hết TIME_BUDGET giây, bấm
  tiếp để lấy tiếp (một request HTTP không được chạy quá lâu). Kiểm quyền admin ở server, không chỉ ẩn nút.
- Sổ hoá đơn đã lấy: kết quả từng hoá đơn (ghi công nợ / đã trả qua đề nghị chi / không khớp đơn / MISA bỏ thanh
  toán)."""

import logging
import time
from urllib.parse import urlencode

from odoo import fields, http
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import format_vn_number, paginate
from odoo.http import request

from ..models.purchase_order import DEBT_CUTOFF_PARAM
from .accountant_page import DEBT_ROUTE, PER_PAGE
from .all_payments_page import AllPaymentsPage

_logger = logging.getLogger(__name__)

MISA_ROUTE = f"{DEBT_ROUTE}/misa"
# Giây tối đa một lần bấm được đọc MISA — dưới giới hạn thời gian request của Odoo.sh, còn chỗ ghi dữ liệu.
TIME_BUDGET = 40
MISA_STATES = ("imported", "covered", "no_order", "unpaid_again")
ADMIN_GROUP = "base.group_system"


class MisaImportPage(AllPaymentsPage):

    @staticmethod
    def _is_admin():
        return request.env.user.has_group(ADMIN_GROUP)

    def _misa_allowed(self):
        """Trang lấy MISA: kế toán chứng từ chi NCC, hoặc admin (có thể không thuộc nhóm kế toán)."""
        return self._allowed() or self._is_admin()

    @staticmethod
    def _admin_only():
        return request.make_response("Chỉ quản trị hệ thống làm được việc này.",
                                     headers=[("Content-Type", "text/plain; charset=utf-8")], status=403)

    @http.route(MISA_ROUTE, type="http", auth="user", methods=["GET"])
    def misa_page(self, ncc=None, tim="", state=None, page=1, msg=None, error=None, quan_tri=None, **_kw):
        if not self._misa_allowed():
            return self._forbidden()
        Invoice = request.env["hlv.misa.purchase.invoice"].sudo()
        vendor = self._vendor(ncc)
        state = state if state in MISA_STATES else ""
        domain = ([("partner_id", "=", vendor.id)] if vendor else []) + ([("state", "=", state)] if state else [])
        pager = paginate(Invoice.search_count(domain), page, PER_PAGE)
        is_admin = self._is_admin()
        round_vendors, pending = Invoice._hlv_round_vendors() if is_admin else ((), ())
        tim = (tim or "").strip()[:64]
        return self._render("hlv_vendor_payment_docs.accountant_misa_import", {
            "page_title": "Lấy hoá đơn đã thanh toán từ MISA",
            "section": "debt",
            "misa_route": MISA_ROUTE,
            "cutoff": request.env["purchase.order"]._hlv_debt_cutoff(),
            "vendor": vendor,
            "tim": tim,
            "vendors": self._find_vendors(tim) if not vendor else (),
            "is_admin": is_admin,
            # Vừa làm việc quản trị (lưu mốc / lấy cho mọi NCC) → mở sẵn khung quản trị để thấy kết quả.
            "admin_open": quan_tri == "1",
            "state": state,
            "state_options": Invoice._fields["state"].selection,
            "invoices": Invoice.search(domain, offset=pager["offset"], limit=pager["limit"]),
            "pager": pager,
            "page_url": lambda **changes: self._misa_url(vendor, state, **changes),
            "round_total": len(round_vendors),
            "round_pending": len(pending),
            "round_start": Invoice._hlv_round_start(),
            "unpaid_again_count": Invoice.search_count([("state", "=", "unpaid_again")]),
            "msg": (msg or "")[:500],
            "error": (error or "")[:800],
        })

    @staticmethod
    def _misa_url(vendor, state, **params):
        query = {"ncc": vendor.id if vendor else "", "state": state}
        query.update(params)
        if str(query.get("page", "")) == "1":
            query.pop("page")
        query = urlencode({key: value for key, value in query.items() if value not in (None, "")})
        return f"{MISA_ROUTE}?{query}" if query else MISA_ROUTE

    @http.route(f"{MISA_ROUTE}/moc", type="http", auth="user", methods=["POST"])
    def misa_cutoff(self, cutoff="", **_kw):
        if not self._is_admin():
            return self._admin_only()
        try:
            day = fields.Date.to_date((cutoff or "").strip())
        except ValueError:
            day = None
        if not day:
            return request.redirect(self._misa_url(None, "", quan_tri=1, error="Ngày mốc công nợ không hợp lệ."))
        request.env["ir.config_parameter"].sudo().set_param(DEBT_CUTOFF_PARAM, day.isoformat())
        return request.redirect(self._misa_url(None, "", quan_tri=1, msg=f"Đã đặt mốc công nợ {day.strftime('%d/%m/%Y')}."))

    def _run_misa(self, work, vendor):
        """Chạy một lần lấy MISA trong savepoint: MISA / mạng lỗi thì bỏ phần đang dở, báo lỗi rõ — không để kế toán
        tưởng "NCC không có hoá đơn nào"."""
        deadline = time.monotonic() + TIME_BUDGET
        try:
            with request.env.cr.savepoint():
                return work(deadline), None
        except Exception as exc:  # MISA trả lỗi / hết phiên / mạng — báo cho kế toán, không 500
            _logger.exception("Lấy hoá đơn MISA lỗi (NCC %s)", vendor.display_name if vendor else "mọi NCC")
            return None, ("Không lấy được dữ liệu MISA: %s — nếu lỗi về phiên đăng nhập thì cookie MISA trong "
                          "misa_fetch_po_button/utils/misa_config.py đã hết hạn, cần chụp lại." % str(exc)[:400])

    @http.route(f"{MISA_ROUTE}/ncc/<int:partner_id>", type="http", auth="user", methods=["POST"])
    def misa_sync_vendor(self, partner_id, **_kw):
        if not self._misa_allowed():
            return self._forbidden()
        vendor = self._vendor(partner_id)
        if not vendor:
            return request.not_found()
        Invoice = request.env["hlv.misa.purchase.invoice"].sudo()
        stats, error = self._run_misa(lambda deadline: Invoice._hlv_sync_one(vendor, deadline), vendor)
        if error:
            return request.redirect(self._misa_url(vendor, "", error=error))
        return request.redirect(self._misa_url(vendor, "", msg=self._vendor_message(vendor, stats)))

    @staticmethod
    def _vendor_message(vendor, stats):
        parts = [f"{vendor.name}: MISA có {stats['found']} hoá đơn từ mốc công nợ, {stats['paid']} đã thanh toán",
                 f"ghi mới {stats['new']} hoá đơn ({format_vn_number(round(stats['debt']))} công nợ)"]
        if stats["unpaid_again"]:
            parts.append(f"{stats['unpaid_again']} hoá đơn MISA đã bỏ thanh toán — xem và huỷ phiếu nếu đúng")
        if stats["pending"]:
            parts.append(f"còn {stats['pending']} hoá đơn chưa kịp đọc — bấm lấy lần nữa")
        return "; ".join(parts) + "."

    @http.route(f"{MISA_ROUTE}/lay-tat-ca", type="http", auth="user", methods=["POST"])
    def misa_sync_round(self, moi=None, **_kw):
        if not self._is_admin():
            return self._admin_only()
        Invoice = request.env["hlv.misa.purchase.invoice"].sudo()
        if moi == "1":
            Invoice._hlv_start_round()
        totals, error = self._run_misa(Invoice._hlv_sync_round, None)
        if error:
            return request.redirect(self._misa_url(None, "", quan_tri=1, error=error))
        _vendors, pending = Invoice._hlv_round_vendors()
        msg = (f"Lấy xong {totals['vendors']} NCC lần này: ghi mới {totals['new']} hoá đơn "
               f"({format_vn_number(round(totals['debt']))} công nợ)"
               + (f", {totals['unpaid_again']} hoá đơn MISA bỏ thanh toán" if totals["unpaid_again"] else "")
               + (f". Còn {len(pending)} NCC — bấm \"Lấy tiếp\"." if pending else ". Đã lấy hết mọi NCC."))
        return request.redirect(self._misa_url(None, "", quan_tri=1, msg=msg))
