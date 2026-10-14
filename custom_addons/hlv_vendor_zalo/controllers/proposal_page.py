# -*- coding: utf-8 -*-
"""Trang sale duyệt đề xuất AI đọc từ Zalo: /zalo-de-xuat/<id>. Chỉ sale của phiếu (mã sale thuộc tài khoản) hoặc nhóm
Quản lý Hỏi giá NCC mở được. "Ghi vào báo giá" gọi đúng hàm NCC dùng khi tự gửi báo giá (_vendor_submit) — cùng luật:
mọi dòng đang mở phải có giá + VAT, hoặc tick hết hàng."""

from markupsafe import Markup
from odoo import fields, http
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_line import VAT_SELECTION
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import format_vn_number, local_date_text
from odoo.addons.hlv_vendor_quotation.services import sale_scope
from odoo.addons.hlv_vendor_quotation.services.access_setup import USER_GROUP
from odoo.addons.hlv_vendor_quotation.services.asset_version import asset_version
from odoo.exceptions import UserError
from odoo.http import request

from ..models.zalo_proposal import REVIEW_ROUTE
from ..services.proposal_apply import submit_values


class ZaloProposalPage(http.Controller):

    @staticmethod
    def _can_open(proposal):
        """Sale của phiếu hoặc quản lý Hỏi giá NCC. Mã sale không thuộc tài khoản → validate_sale_code ném UserError."""
        env = request.env
        if not env.user.has_group(USER_GROUP):
            return False
        if sale_scope.can_see_all(env):
            return True
        try:
            sale_scope.validate_sale_code(env, proposal.sale_code or "")
        except UserError:
            return False
        return True

    def _proposal(self, proposal_id):
        proposal = request.env["hlv.zalo.proposal"].sudo().browse(proposal_id).exists()
        return proposal if proposal and self._can_open(proposal) else None

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
            errors = self._apply(proposal, form)
            if not errors:
                return request.redirect(f"{REVIEW_ROUTE}/{proposal.id}?saved=applied")
        return request.render("hlv_vendor_zalo.proposal_page", {
            "doctype": Markup("<!DOCTYPE html>"),
            "asset_version": asset_version(),
            "company": request.env.company.sudo(),
            "proposal": proposal,
            "rows": self._rows(proposal, form if errors else None),
            "errors": errors,
            "saved": form.get("saved") or "",
            "vat_options": VAT_SELECTION,
            "fmt": format_vn_number,
            "fdate": local_date_text,
        })

    @staticmethod
    def _rows(proposal, posted):
        """Mỗi dòng báo giá đang mở một hàng: điền sẵn từ đề xuất AI; dòng NCC chưa nói tới điền giá đang có trên báo giá
        (nếu có); vừa bấm Ghi mà lỗi thì giữ đúng chữ sale đã gõ."""
        by_line = {l.quote_line_id.id: l for l in proposal.line_ids}
        rows = []
        for line in proposal.quote_id._vendor_lines().filtered(lambda l: not l.vendor_locked):
            ai = by_line.get(line.id)
            if ai:
                prefill = {
                    "unavailable": ai.status == "unavailable",
                    "price": format_vn_number(ai.price_incl) if ai.price_incl else "",
                    "vat": ai.vat or "", "discount": format_vn_number(ai.discount) if ai.discount else "",
                    "available": format_vn_number(ai.available_qty) if ai.available_qty >= 0 else "",
                    "backorder_date": ai.backorder_date.isoformat() if ai.backorder_date else "",
                    "delivery_days": str(ai.delivery_days or ""),
                }
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

    @staticmethod
    def _apply(proposal, form):
        """Ghi vào báo giá. Trả danh sách lỗi ([] = đã ghi)."""
        quote = proposal.quote_id
        today = quote._vendor_today()
        values, errors = {}, []
        for line in quote._vendor_lines().filtered(lambda l: not l.vendor_locked):
            raw_date = (form.get(f"backorder_date_{line.id}") or "").strip()
            try:
                backorder = fields.Date.to_date(raw_date) if raw_date else None
            except ValueError:
                errors.append(f"{line.name}: ngày hẹn \"{raw_date}\" không đọc được")
                continue
            line_values, error = submit_values(line.product_qty, {
                "unavailable": bool(form.get(f"na_{line.id}")), "price": form.get(f"price_{line.id}"),
                "vat": form.get(f"vat_{line.id}"), "discount": form.get(f"discount_{line.id}"),
                "available": form.get(f"available_{line.id}"), "backorder_date": backorder,
                "delivery_days": form.get(f"delivery_days_{line.id}"),
            }, today, {"vendor_note": line.vendor_note, "invoice_name": line.invoice_name})
            if error:
                errors.append(f"{line.product_id.default_code or line.name}: {error}")
            else:
                values[line.id] = line_values
        if errors:
            return errors
        # Hiệu lực giá cũ đã qua thì để trống — _vendor_submit tự đặt 7 ngày (ngày đã qua là lỗi).
        valid_until = quote.price_valid_until if quote.price_valid_until and quote.price_valid_until >= today else False
        try:
            quote._vendor_submit(values, quote.vendor_note or "", valid_until)
        except UserError as exc:
            return [exc.args[0]]
        proposal._mark("applied")
        proposal._log_applied()
        return []
