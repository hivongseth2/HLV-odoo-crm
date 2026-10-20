# -*- coding: utf-8 -*-
"""Trang sale duyệt đề xuất AI đọc từ Zalo: /zalo-de-xuat/<id>. Chỉ sale của phiếu (mã sale thuộc tài khoản) hoặc nhóm
Quản lý Hỏi giá NCC mở được. "Ghi vào báo giá" (zalo_proposal._apply_form) gọi đúng hàm NCC dùng khi tự gửi báo giá (_vendor_submit) — cùng luật:
mọi dòng đang mở phải có giá + VAT, hoặc tick hết hàng."""

from datetime import timedelta

from markupsafe import Markup
from odoo import fields, http
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_line import VAT_SELECTION
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import format_vn_number, local_date_text
from odoo.addons.hlv_vendor_quotation.services import sale_scope
from odoo.addons.hlv_vendor_quotation.services.access_setup import USER_GROUP
from odoo.addons.hlv_vendor_quotation.services.asset_version import asset_version
from odoo.http import request

from ..models.zalo_proposal import PROPOSAL_STATES, REVIEW_ROUTE

# Danh sách: đề xuất chờ duyệt hiện hết; đã ghi / đã bỏ chỉ giữ chừng này ngày cho đỡ dài.
LIST_DECIDED_DAYS = 30
LIST_LIMIT = 300


class ZaloProposalPage(http.Controller):

    @staticmethod
    def _can_open(proposal):
        """Sale của phiếu hoặc quản lý Hỏi giá NCC (sale_scope.can_handle_sale_code)."""
        env = request.env
        return env.user.has_group(USER_GROUP) and sale_scope.can_handle_sale_code(env, proposal.sale_code)

    def _proposal(self, proposal_id):
        proposal = request.env["hlv.zalo.proposal"].sudo().browse(proposal_id).exists()
        return proposal if proposal and self._can_open(proposal) else None

    def _page_values(self):
        return {
            "doctype": Markup("<!DOCTYPE html>"),
            "asset_version": asset_version(),
            "company": request.env.company.sudo(),
            "fmt": format_vn_number,
            "fdate": local_date_text,
        }

    @http.route(REVIEW_ROUTE, type="http", auth="user", methods=["GET"])
    def proposal_list(self, **_kw):
        """Đề xuất tài khoản này duyệt được — lọc bằng đúng luật của trang duyệt (_can_open)."""
        if not request.env.user.has_group(USER_GROUP):
            return request.not_found()
        since = fields.Datetime.now() - timedelta(days=LIST_DECIDED_DAYS)
        candidates = request.env["hlv.zalo.proposal"].sudo().search(
            ["|", ("state", "=", "draft"), ("ai_run_at", ">=", since)], limit=LIST_LIMIT)
        proposals = candidates.filtered(self._can_open).sorted(lambda p: (p.state != "draft", -p.id))
        return request.render("hlv_vendor_zalo.proposal_list_page", dict(
            self._page_values(), proposals=proposals, states=dict(PROPOSAL_STATES), keep_days=LIST_DECIDED_DAYS))

    @http.route(f"{REVIEW_ROUTE}/<int:proposal_id>", type="http", auth="user", methods=["GET", "POST"])
    def proposal_page(self, proposal_id, action=None, **form):
        proposal = self._proposal(proposal_id)
        if not proposal:
            return request.not_found()
        errors = []
        if request.httprequest.method == "POST" and proposal.state == "draft":
            if action == "reject":
                proposal._mark("rejected")
                return request.redirect(f"{REVIEW_ROUTE}/{proposal.id}?saved=rejected")
            errors = proposal._apply_form(form)
            if not errors:
                proposal._log_applied()
                return request.redirect(f"{REVIEW_ROUTE}/{proposal.id}?saved=applied")
        return request.render("hlv_vendor_zalo.proposal_page", dict(
            self._page_values(),
            proposal=proposal,
            rows=self._rows(proposal, form if errors else None),
            errors=errors,
            saved=form.get("saved") or "",
            vat_options=VAT_SELECTION,
        ))

    @http.route(f"{REVIEW_ROUTE}/<int:proposal_id>/anh/<int:attachment_id>", type="http", auth="user", methods=["GET"])
    def proposal_image(self, proposal_id, attachment_id):
        """Ảnh NCC gửi trong nhóm, xem trên trang duyệt. Sale thường không có quyền đọc tin Zalo ở backend nên không dùng
        /web/image — chỉ trả ảnh thuộc tin của đúng đề xuất người này mở được."""
        proposal = self._proposal(proposal_id)
        if not proposal:
            return request.not_found()
        messages = proposal.message_ids | proposal.line_ids.evidence_message_ids
        attachment = messages._image_attachments().filtered(lambda a: a.id == attachment_id)
        if not attachment:
            return request.not_found()
        return request.make_response(attachment.raw, [
            ("Content-Type", attachment.mimetype), ("Cache-Control", "private, max-age=86400"),
            ("X-Content-Type-Options", "nosniff"),
        ])

    @staticmethod
    def _rows(proposal, posted):
        """Mỗi dòng báo giá đang mở một hàng: điền sẵn từ đề xuất AI; dòng NCC chưa nói tới điền giá đang có trên báo giá
        (nếu có); vừa bấm Ghi mà lỗi thì giữ đúng chữ sale đã gõ."""
        by_line = {l.quote_line_id.id: l for l in proposal.line_ids}
        rows = []
        for line in proposal._open_lines():
            ai = by_line.get(line.id)
            if ai:
                prefill = ai._form_values()
                prefill["unavailable"] = prefill.pop("na")
            else:
                current = line.list_price or line.price_unit
                prefill = {
                    "unavailable": line.unavailable,
                    "price": format_vn_number(round(current * (1 + line.tax_rate / 100.0))) if current else "",
                    "vat": line.vat or "", "discount": format_vn_number(line.discount) if line.list_price else "",
                    "available": format_vn_number(line.available_qty) if (line.backorder_date or line.no_more) else "",
                    "backorder_date": line.backorder_date.isoformat() if line.backorder_date else "",
                    "delivery_days": str(line.delivery_days or ""),
                }
            if posted is not None:
                prefill = {
                    "unavailable": bool(posted.get(f"na_{line.id}")),
                    **{key: posted.get(f"{key}_{line.id}") or "" for key in
                       ("price", "vat", "discount", "available", "backorder_date", "delivery_days")},
                }
            rows.append({"line": line, "ai": ai, "value": prefill})
        return rows
