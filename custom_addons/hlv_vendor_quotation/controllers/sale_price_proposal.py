# -*- coding: utf-8 -*-
"""Trang /hoi-gia-ncc: sale xử lý đề xuất giá của thu mua (models/po_price_proposal.py) — hỏi lại NCC, gửi giá NCC
báo lại cho thu mua duyệt, hoặc báo NCC giữ giá. Trả lại chi tiết phiếu như các thao tác khác trên phiếu."""

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..services import sale_page_payload as payload
from ..services.price_proposal_payload import vat_options
from .sale_page_common import API, SalePageMixin, to_int


class VendorQuotePriceProposal(SalePageMixin, http.Controller):

    def _proposal(self, code, proposal_id):
        """Đề xuất thuộc phiếu trong phạm vi mã sale → (đề xuất (sudo — sale không có quyền model này), phiếu)."""
        scope = self._check(code)
        proposal = request.env["hlv.po.price.proposal"].sudo().browse(to_int(proposal_id)).exists()
        if not proposal or not proposal.inquiry_id:
            raise UserError("Không tìm thấy đề xuất giá.")
        return proposal, self._get_inquiry(proposal.inquiry_id.id, scope)

    @http.route(f"{API}/price_requote", type="json", auth="user", methods=["POST"])
    def api_price_requote(self, code="", proposal_id=None, qty=0, product_id=None, needs_vendor=True, price=0,
                          note="", vat="", **kw):
        """Sale chốt SL / mã rồi gửi: hỏi lại NCC (mở món trên báo giá NCC + nhắn NCC) hoặc gửi thẳng thu mua duyệt."""
        proposal, inquiry = self._proposal(code, proposal_id)
        product = request.env["product.product"].sudo().browse(to_int(product_id)).exists()
        try:
            qty, price = float(qty or 0), float(price or 0)
        except (TypeError, ValueError):
            raise UserError("Số lượng / giá không hợp lệ.") from None
        vat = str(vat or "")
        company = proposal.purchase_order_id.company_id
        if vat and vat not in {o["code"] for o in vat_options(company)}:
            raise UserError("Công ty chưa khai thuế mua mức VAT này — chọn mức khác.")
        proposal._sale_send(qty, product, bool(needs_vendor), max(price, 0.0), str(note or "")[:1000], vat)
        return payload.inquiry_detail(inquiry)

    @http.route(f"{API}/price_submit", type="json", auth="user", methods=["POST"])
    def api_price_submit(self, code="", proposal_id=None, note="", **kw):
        """Sale gửi giá NCC vừa báo lại cho thu mua duyệt."""
        proposal, inquiry = self._proposal(code, proposal_id)
        proposal._sale_submit(str(note or ""))
        return payload.inquiry_detail(inquiry)

    @http.route(f"{API}/price_keep", type="json", auth="user", methods=["POST"])
    def api_price_keep(self, code="", proposal_id=None, note="", **kw):
        """Sale báo NCC giữ giá cũ — đóng đề xuất."""
        proposal, inquiry = self._proposal(code, proposal_id)
        proposal._sale_keep(str(note or ""))
        return payload.inquiry_detail(inquiry)
