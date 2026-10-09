# -*- coding: utf-8 -*-
"""Trang /hoi-gia-ncc — tạo phiếu hỏi giá và các ô tìm của hộp "Hỏi giá NCC"."""

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.osv import expression

from ..services import sale_page_payload as payload
from ..services import sale_scope
from ..services.price_history import quoted_prices
from ..services.product_paste import match_pasted
from ..services.sale_code import SALE_CODE_FIELD, has_sale_code
from .sale_page_common import API, SEARCH_LIMIT, SalePageMixin, to_int

PASTE_MAX_CHARS = 20000


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

    @http.route(f"{API}/parse_products", type="json", auth="user", methods=["POST"])
    def api_parse_products(self, text="", **kw):
        """Danh sách hàng sale dán từ Zalo / Excel → từng dòng kèm sản phẩm dò được."""
        self._check()
        return {"rows": match_pasted(request.env, (text or "")[:PASTE_MAX_CHARS])}

    @http.route(f"{API}/price_history", type="json", auth="user", methods=["POST"])
    def api_price_history(self, product_ids=None, search="", **kw):
        """Giá NCC đã báo cho sản phẩm — mọi mã sale (cố ý: để khỏi hỏi giá trùng). Chỉ cần quyền
        vào trang; không mở được phiếu của sale khác (xem services/price_history.py)."""
        self._check()
        ids = [to_int(i) for i in (product_ids or []) if to_int(i)]
        return {"products": quoted_prices(request.env, product_ids=ids, search=(search or "").strip()[:100])}

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

    @http.route(f"{API}/create", type="json", auth="user", methods=["POST"])
    def api_create(self, code="", lines=None, vendor_ids=None,
                   deadline=None, note="", reuse=None, request_now=False, opportunity_ref="", **kw):
        """Tạo phiếu hỏi giá + mỗi NCC một báo giá. Trả tin nhắn Zalo cho từng NCC.

        code là mã sale của phiếu. "Tất cả" không phải một mã: thu mua tạo phiếu khi đang xem
        tất cả thì phiếu không gắn mã sale.
        reuse: {product_id: vendor_id} — giá dùng lại sale đã chọn ("Dùng giá này"); NCC đó
        được thêm vào phiếu và giá được chọn sẵn. request_now: mọi sản phẩm đều dùng lại giá →
        chỉ gửi các NCC đó và lên YCMH luôn, không hỏi giá ai.
        """
        self._check()
        env = request.env
        sale_code = "" if code == sale_scope.ALL_SALES else sale_scope.validate_sale_code(env, code)
        if code == sale_scope.ALL_SALES and not sale_scope.can_see_all(env):
            raise UserError("Chọn mã sale của bạn trước khi hỏi giá.")
        choices = {to_int(p): to_int(v) for p, v in (reuse or {}).items() if to_int(p) and to_int(v)}
        vendor_ids = list(choices.values()) if request_now else list(vendor_ids or []) + list(choices.values())
        partners = env["res.partner"].browse([to_int(v) for v in vendor_ids]).exists()
        inquiry = env["hlv.vendor.inquiry"]._create_with_quotes(
            partners,
            self._line_vals(lines or []),
            sale_code,
            date_deadline=fields.Date.to_date(deadline) if deadline else False,
            note=(note or "").strip() or False,
            opportunity_ref=opportunity_ref,
        )
        missing = inquiry._apply_reuse_choices(choices) if choices else inquiry.line_ids.browse()
        request_name = ""
        if request_now and not missing:
            purchase_request, _merged = inquiry.action_create_request()
            request_name = purchase_request.name
        return {
            "inquiry": payload.inquiry_summary(inquiry),
            "request": request_name,
            # Giá dùng lại không chọn được (vừa bị phiếu khác giữ / hết hạn) — phiếu vẫn tạo,
            # NCC báo giá như bình thường.
            "reuse_missing": [line.name or line.product_id.display_name for line in missing],
            "results": [payload.quote_share_result(q) for q in inquiry.quote_ids],
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
