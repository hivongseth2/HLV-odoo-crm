# -*- coding: utf-8 -*-
"""Trang /hoi-gia-ncc — tạo phiếu hỏi giá và các ô tìm của hộp "Hỏi giá NCC"."""

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.osv import expression

from ..services import sale_page_payload as payload
from ..services import sale_scope
from ..services.sale_code import SALE_CODE_FIELD, has_sale_code
from .sale_page_common import API, SEARCH_LIMIT, SalePageMixin, to_int


class VendorQuoteSalePageCreate(SalePageMixin, http.Controller):

    @http.route(f"{API}/products", type="json", auth="user", methods=["POST"])
    def api_products(self, search="", **kw):
        self._check()
        search = (search or "").strip()
        if not search:
            return {"products": []}
        products = request.env["product.product"].search([
            ("purchase_ok", "=", True),
            "|", "|", ("default_code", "ilike", search), ("name", "ilike", search),
            ("barcode", "=", search),
        ], limit=SEARCH_LIMIT)
        return {"products": [payload.product_payload(p) for p in products]}

    @http.route(f"{API}/partners", type="json", auth="user", methods=["POST"])
    def api_partners(self, search="", **kw):
        self._check()
        search = (search or "").strip()
        if not search:
            return {"partners": []}
        partners = request.env["res.partner"].search(
            request.env["hlv.vendor.quote.access"]._vendor_search_domain(search),
            order="supplier_rank desc, name", limit=SEARCH_LIMIT,
        )
        # Kèm MST: danh bạ có nhiều công ty trùng tên, chỉ nhìn tên thì không biết chọn ai.
        return {"partners": [{"id": p.id, "name": p.display_name, "vat": p.vat or ""} for p in partners]}

    @http.route(f"{API}/suggest", type="json", auth="user", methods=["POST"])
    def api_suggest(self, product_ids=None, **kw):
        self._check()
        products = request.env["product.product"].browse(
            [to_int(pid) for pid in product_ids or []]
        ).exists()
        items = request.env["hlv.vendor.suggestion"].suggest(products)
        names = {p.id: p.display_name for p in request.env["res.partner"].browse([i["partner_id"] for i in items])}
        return {"suggestions": [
            dict(payload.suggestion_payload(item, products), name=names.get(item["partner_id"], ""))
            for item in items
        ]}

    @http.route(f"{API}/sale_orders", type="json", auth="user", methods=["POST"])
    def api_sale_orders(self, search="", **kw):
        """Đơn bán để lấy sẵn hàng / gắn vào phiếu. Không sudo: sale chỉ thấy đơn mình được xem."""
        self._check()
        search = (search or "").strip()
        if not search:
            return {"orders": []}
        domains = [
            [("name", "ilike", search)],
            [("client_order_ref", "ilike", search)],
            [("partner_id", "ilike", search)],
        ]
        if has_sale_code(request.env):
            domains.append([(SALE_CODE_FIELD, "ilike", search)])
        orders = request.env["sale.order"].search(
            expression.AND([[("state", "!=", "cancel")], expression.OR(domains)]),
            order="id desc", limit=SEARCH_LIMIT,
        )
        return {"orders": [payload.sale_order_summary(o) for o in orders]}

    @http.route(f"{API}/sale_order_lines", type="json", auth="user", methods=["POST"])
    def api_sale_order_lines(self, order_id=None, **kw):
        """Hàng hoá của một đơn bán để đổ sẵn vào phiếu hỏi giá."""
        self._check()
        order = request.env["sale.order"].browse(to_int(order_id)).exists()
        if not order:
            raise UserError("Không tìm thấy đơn bán.")
        lines = order.order_line.filtered(
            lambda l: not l.display_type and not l.is_downpayment
            and l.product_id.purchase_ok and l.product_uom_qty > 0
        )
        return {
            "order": payload.sale_order_summary(order),
            "lines": [payload.sale_line_payload(line) for line in lines],
        }

    @http.route(f"{API}/create", type="json", auth="user", methods=["POST"])
    def api_create(self, code="", lines=None, vendor_ids=None, sale_order_id=None,
                   deadline=None, note="", **kw):
        """Tạo phiếu hỏi giá + mỗi NCC một báo giá. Trả tin nhắn Zalo cho từng NCC.

        code là mã sale của phiếu. "Tất cả" không phải một mã: thu mua tạo phiếu khi đang xem
        tất cả thì phiếu không gắn mã sale.
        """
        self._check()
        env = request.env
        sale_code = "" if code == sale_scope.ALL_SALES else sale_scope.validate_sale_code(env, code)
        if code == sale_scope.ALL_SALES and not sale_scope.can_see_all(env):
            raise UserError("Chọn mã sale của bạn trước khi hỏi giá.")
        partners = env["res.partner"].browse([to_int(v) for v in vendor_ids or []]).exists()
        order = env["sale.order"].browse(to_int(sale_order_id)).exists()
        inquiry = env["hlv.vendor.inquiry"]._create_with_quotes(
            partners,
            self._line_vals(lines or []),
            sale_code,
            sale_order=order or None,
            date_deadline=fields.Date.to_date(deadline) if deadline else False,
            note=(note or "").strip() or False,
        )
        return {
            "inquiry": payload.inquiry_summary(inquiry),
            "results": [
                {
                    "vendor_name": q.partner_id.commercial_partner_id.display_name,
                    "name": q.name,
                    "share_message": payload.share_message(q),
                }
                for q in inquiry.quote_ids
            ],
        }

    def _line_vals(self, raw_lines):
        """Dòng sale gửi lên → dòng phiếu hỏi giá. ĐVT sai nhóm với sản phẩm thì lấy ĐVT mua."""
        env = request.env
        vals_list = []
        for index, raw in enumerate(raw_lines, start=1):
            product = env["product.product"].browse(to_int(raw.get("product_id"))).exists()
            try:
                qty = float(raw.get("qty") or 0)
            except (TypeError, ValueError):
                qty = 0
            if not product or qty <= 0:
                raise UserError(f"Dòng {index}: thiếu sản phẩm hoặc số lượng phải lớn hơn 0.")
            default_uom = product.uom_po_id or product.uom_id
            uom = env["uom.uom"].browse(to_int(raw.get("uom_id"))).exists()
            if not uom or uom.category_id != default_uom.category_id:
                uom = default_uom
            vals_list.append({
                "product_id": product.id,
                "name": (raw.get("name") or product.display_name)[:255],
                "product_qty": qty,
                "product_uom_id": uom.id,
            })
        return vals_list
