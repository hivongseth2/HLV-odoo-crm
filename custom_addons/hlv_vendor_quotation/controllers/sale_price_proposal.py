# -*- coding: utf-8 -*-
"""Trang /hoi-gia-ncc: sale xử lý đề xuất giá của thu mua (models/po_price_proposal.py) — hỏi lại NCC, gửi giá NCC
báo lại cho thu mua duyệt, hoặc báo NCC giữ giá. Trả lại chi tiết phiếu như các thao tác khác trên phiếu."""

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..services import sale_page_payload as payload
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
    def api_price_requote(self, code="", proposal_id=None, message="", **kw):
        """Sale hỏi lại NCC giá món thu mua đề xuất: mở món trên báo giá NCC + nhắn NCC."""
        proposal, inquiry = self._proposal(code, proposal_id)
        proposal._sale_requote(str(message or "")[:1000])
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
