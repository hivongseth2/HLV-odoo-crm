# -*- coding: utf-8 -*-
"""Trang xác nhận gợi ý khớp mã NCC của một báo giá: /khop-ma-ncc/<id báo giá>. Sale của phiếu hỏi giá hoặc quản lý
Hỏi giá NCC mở được (sale_scope.can_handle_sale_code) — link hiện ở dòng NCC trên trang /hoi-gia-ncc."""

from markupsafe import Markup
from odoo import http
from odoo.addons.hlv_vendor_quotation.services import sale_scope
from odoo.addons.hlv_vendor_quotation.services.access_setup import USER_GROUP
from odoo.addons.hlv_vendor_quotation.services.asset_version import asset_version
from odoo.http import request

from ..models.vendor_code_suggestion import SUGGESTION_ROUTE


class CodeSuggestionPage(http.Controller):

    @http.route(f"{SUGGESTION_ROUTE}/<int:quote_id>", type="http", auth="user", methods=["GET", "POST"])
    def suggestion_page(self, quote_id, suggestion=None, action=None, **_kw):
        env = request.env
        quote = env["hlv.vendor.quote"].sudo().browse(quote_id).exists()
        if not quote or not env.user.has_group(USER_GROUP) \
                or not sale_scope.can_handle_sale_code(env, quote.inquiry_id.sale_code):
            return request.not_found()
        Suggestion = env["hlv.vendor.code.suggestion"].sudo()
        if request.httprequest.method == "POST" and suggestion and action in ("confirm", "reject"):
            # sudo chỉ bỏ kiểm quyền — env.user vẫn là người đang đăng nhập, ghi đúng "người xác nhận".
            picked = Suggestion.search([("id", "=", int(suggestion)), ("quote_id", "=", quote.id)])
            if action == "confirm":
                picked.action_confirm()
            else:
                picked.action_reject()
            return request.redirect(f"{SUGGESTION_ROUTE}/{quote.id}")
        suggestions = Suggestion.search([("quote_id", "=", quote.id), ("state", "in", ("pending", "confirmed", "rejected"))])
        # Mã NCC đã được gắn ở chỗ khác (trùng mã, gợi ý khác) thì gợi ý còn chờ không còn việc.
        pending = suggestions.filtered(lambda s: s.state == "pending" and not s.price_id.product_id)
        return request.render("hlv_vendor_import.code_suggestion_page", {
            "doctype": Markup("<!DOCTYPE html>"),
            "asset_version": asset_version(),
            "company": env.company.sudo(),
            "quote": quote,
            "pending": pending,
            "decided": suggestions.filtered(lambda s: s.state != "pending"),
            "route": SUGGESTION_ROUTE,
        })
