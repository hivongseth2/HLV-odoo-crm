# -*- coding: utf-8 -*-
"""Trang /hoi-gia-ncc: sale hỏi giá NCC ngoài backend, cùng kiểu /sale_plan, /delivery_plan.

Chạy bằng quyền của user đăng nhập (không sudo), nên ACL / record rule vẫn áp. Chỗ cần
đọc đơn mua (gợi ý NCC, số đã lên PO) đã tự sudo trong model, có ghi lý do ở đó.
"""

from collections import defaultdict

from odoo import fields, http
from odoo.exceptions import AccessError, UserError
from odoo.osv import expression
from odoo.http import request

from ..models.vendor_quote_access import SALE_PAGE_ROUTE as PAGE_ROUTE
from ..models.vendor_quote_line import SELECTOR_GROUP, VAT_SELECTION
from ..models.vendor_quote_utils import paginate
from ..services import sale_page_payload as payload
from ..services.sale_code import SALE_CODE_FIELD, has_sale_code

API = "/api/hoi-gia-ncc"
PAGE_GROUPS = (
    "sales_team.group_sale_salesman",
    "purchase.group_purchase_user",
    "purchase_request.group_purchase_request_user",
)
PER_PAGE = 30
SEARCH_LIMIT = 20
# Cột NCC không tải hết danh bạ NCC: hiện chừng này, còn lại sale gõ tên để tìm.
VENDOR_LIMIT = 40
# Tab lọc: (mã, nhãn). waiting/quoted/expired dùng domain trạng thái của model.
STATUS_TABS = [
    ("all", "Tất cả"),
    ("waiting", "Chờ NCC báo giá"),
    ("quoted", "NCC đã báo giá"),
    ("expired", "Quá hạn"),
    ("done", "Đã đóng"),
    ("draft", "Nháp"),
    ("cancel", "Đã huỷ"),
]
QUOTE_ACTIONS = {"close": "action_close", "reopen": "action_reopen", "cancel": "action_cancel"}


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class VendorQuoteSalePage(http.Controller):

    @http.route(PAGE_ROUTE, type="http", auth="user", methods=["GET"])
    def sale_page(self, ncc=None, **kw):
        return request.render("hlv_vendor_quotation.sale_page", {
            "user_name": request.env.user.name,
            "allowed": self._allowed(),
            "initial_vendor_id": _to_int(ncc),
        })

    @http.route(f"{API}/config", type="json", auth="user", methods=["POST"])
    def api_config(self, **kw):
        self._check()
        today = fields.Date.context_today(request.env.user)
        return {
            "can_select": request.env.user.has_group(SELECTOR_GROUP),
            "vat_options": VAT_SELECTION,
            "status_tabs": STATUS_TABS,
            "today": fields.Date.to_string(today),
        }

    @http.route(f"{API}/vendors", type="json", auth="user", methods=["POST"])
    def api_vendors(self, search="", mine=True, include_id=None, **kw):
        """NCC ở cột trái, theo công ty NCC (res.partner gốc).

        Không gõ tìm: NCC đang có báo giá (trong phạm vi đang xem) lên đầu, rồi NCC hay mua
        nhất, tối đa VENDOR_LIMIT. Có gõ: tìm trong toàn bộ NCC theo tên / mã / MST.
        """
        self._check()
        env = request.env
        Access = env["hlv.vendor.quote.access"]
        counts = defaultdict(dict)
        for access, state, count in env["hlv.vendor.quote"]._read_group(
            self._scope_domain(mine), ["access_id", "state"], ["__count"]
        ):
            if access:
                counts[access.partner_id.id][state] = count

        search = (search or "").strip()
        Partner = env["res.partner"]
        if search:
            partners = Partner.search(
                Access._vendor_search_domain(search), order="supplier_rank desc, name", limit=VENDOR_LIMIT,
            )
        else:
            quoted = Partner.browse(list(counts)).exists()
            partners = quoted | Partner.search(
                expression.AND([Access._vendor_partner_domain(), [("id", "not in", quoted.ids)]]),
                order="supplier_rank desc, name", limit=max(VENDOR_LIMIT - len(quoted), 0),
            )
        include = Partner.browse(_to_int(include_id)).exists()
        partners = include | partners

        accesses = {a.partner_id.id: a for a in Access.search([("partner_id", "in", partners.ids)])}
        vendors = [
            payload.vendor_summary(p, accesses.get(p.id, Access), counts.get(p.id, {}))
            for p in partners
        ]
        vendors.sort(key=lambda v: (v["id"] != include.id, -v["quoted"], -v["waiting"], -v["total"]))
        return {"vendors": vendors, "limited": len(partners) >= VENDOR_LIMIT}

    @http.route(f"{API}/quotes", type="json", auth="user", methods=["POST"])
    def api_quotes(self, vendor_id=None, status="all", search="", mine=True, page=1, **kw):
        self._check()
        Quote = request.env["hlv.vendor.quote"]
        base = self._scope_domain(mine) + self._search_domain(search)
        if _to_int(vendor_id):
            base.append(("access_id.partner_id", "=", _to_int(vendor_id)))
        counts = {key: Quote.search_count(base + self._status_domain(key)) for key, _label in STATUS_TABS}
        status = status if status in counts else "all"
        pager = paginate(counts[status], page, PER_PAGE)
        quotes = Quote.search(
            base + self._status_domain(status), order="id desc",
            offset=pager["offset"], limit=pager["limit"],
        )
        return {
            "quotes": [payload.quote_summary(q) for q in quotes],
            "counts": counts,
            "status": status,
            "pager": pager,
        }

    @http.route(f"{API}/quote", type="json", auth="user", methods=["POST"])
    def api_quote(self, quote_id=None, **kw):
        self._check()
        return payload.quote_detail(self._get_quote(quote_id))

    @http.route(f"{API}/quote_action", type="json", auth="user", methods=["POST"])
    def api_quote_action(self, quote_id=None, action="", **kw):
        self._check()
        quote = self._get_quote(quote_id)
        if action not in QUOTE_ACTIONS:
            raise UserError("Thao tác không hợp lệ.")
        getattr(quote, QUOTE_ACTIONS[action])()
        return payload.quote_detail(quote)

    @http.route(f"{API}/requests", type="json", auth="user", methods=["POST"])
    def api_requests(self, search="", **kw):
        self._check()
        domain = [("state", "not in", ("done", "rejected"))]
        search = (search or "").strip()
        if search:
            domain += ["|", "|", ("name", "ilike", search), ("origin", "ilike", search),
                       ("sale_order_id.name", "ilike", search)]
        requests_ = request.env["purchase.request"].search(domain, order="id desc", limit=SEARCH_LIMIT)
        return {"requests": [payload.request_summary(r) for r in requests_]}

    @http.route(f"{API}/request_lines", type="json", auth="user", methods=["POST"])
    def api_request_lines(self, request_id=None, **kw):
        self._check()
        pr = request.env["purchase.request"].browse(_to_int(request_id)).exists()
        if not pr:
            raise UserError("Không tìm thấy Yêu cầu mua hàng.")
        lines = request.env["hlv.vendor.quote"]._quotable_request_lines(pr)
        return {
            "request": payload.request_summary(pr),
            # purchased_qty tính từ đơn mua — sale không đọc được đơn mua, xem _quotable_request_lines.
            "lines": [
                payload.request_line_payload(line, line.product_qty - line.sudo().purchased_qty)
                for line in lines
            ],
        }

    @http.route(f"{API}/sale_orders", type="json", auth="user", methods=["POST"])
    def api_sale_orders(self, search="", **kw):
        """Đơn bán để hỏi giá theo đơn. Không sudo: sale chỉ thấy đơn mình được xem."""
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
        """Hàng hoá của một đơn bán + các YCMH đang mở của đơn (để sale chọn nếu muốn)."""
        self._check()
        order = request.env["sale.order"].browse(_to_int(order_id)).exists()
        if not order:
            raise UserError("Không tìm thấy đơn bán.")
        lines = order.order_line.filtered(
            lambda l: not l.display_type and not l.is_downpayment
            and l.product_id.purchase_ok and l.product_uom_qty > 0
        )
        requests_ = request.env["purchase.request"].search([
            ("sale_order_id", "=", order.id),
            ("state", "not in", ("done", "rejected")),
        ])
        merge_into = request.env["purchase.request"]._mergeable_for_sale_order(order)
        return {
            "order": dict(
                payload.sale_order_summary(order, requests_),
                merge_request=payload.request_summary(merge_into) if merge_into else None,
            ),
            "lines": [payload.sale_line_payload(line) for line in lines],
        }

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
    def api_suggest(self, product_ids=None, request_id=None, **kw):
        self._check()
        products = request.env["product.product"].browse(
            [_to_int(pid) for pid in product_ids or []]
        ).exists()
        pr = request.env["purchase.request"].browse(_to_int(request_id)).exists()
        # NCC đã hỏi cho YCMH này vẫn gợi ý: chọn lại thì hàng mới được bổ sung vào báo giá cũ.
        quoted = request.env["hlv.vendor.quote"]._vendors_with_open_quote(pr)
        items = request.env["hlv.vendor.suggestion"].suggest(products)
        names = {p.id: p.display_name for p in request.env["res.partner"].browse([i["partner_id"] for i in items])}
        return {
            "suggestions": [
                dict(payload.suggestion_payload(item, products), name=names.get(item["partner_id"], ""))
                for item in items
            ],
            "quoted_vendor_ids": quoted.ids,
        }

    @http.route(f"{API}/create", type="json", auth="user", methods=["POST"])
    def api_create(self, lines=None, vendor_ids=None, request_id=None, sale_order_id=None,
                   deadline=None, note="", **kw):
        """Gửi báo giá cho các NCC. Có đơn bán mà chưa chọn YCMH → đưa hàng vào YCMH trước:
        gộp vào YCMH chưa duyệt của đơn, không có thì tạo YCMH mới. Cùng một transaction:
        báo giá lỗi thì YCMH cũng không bị đụng."""
        self._check()
        env = request.env
        pr = env["purchase.request"].browse(_to_int(request_id)).exists()
        partners = env["res.partner"].browse([_to_int(v) for v in vendor_ids or []]).exists()
        if not partners:
            raise UserError("Chọn ít nhất một nhà cung cấp.")
        Quote = env["hlv.vendor.quote"]
        line_vals = self._line_vals(lines or [], pr)
        request_result = None
        order = env["sale.order"].browse(_to_int(sale_order_id)).exists()
        if order and not pr:
            pr, request_lines, merged = env["purchase.request"]._add_sale_order_lines(order, [
                {
                    "product_id": vals["product_id"],
                    "name": vals["name"],
                    "product_qty": vals["product_qty"],
                    "product_uom_id": vals["product_uom_id"],
                }
                for vals in line_vals
            ])
            # Báo giá theo dòng YCMH: dòng vừa gộp hỏi giá cho TỔNG số lượng của dòng đó.
            line_vals = Quote._line_vals_from_request_lines(request_lines)
            request_result = dict(payload.request_summary(pr), merged=merged)
        quotes = Quote._create_and_send(
            partners,
            line_vals,
            pr or None,
            fields.Date.to_date(deadline) if deadline else False,
            (note or "").strip() or False,
        )
        return {
            "results": [
                dict(payload.quote_summary(q), share_message=payload.share_message(q),
                     portal_url=q.portal_quote_url, password=q.portal_password)
                for q in quotes
            ],
            "request_result": request_result,
        }

    # ------------------------------------------------------------------
    def _allowed(self):
        user = request.env.user
        return any(user.has_group(group) for group in PAGE_GROUPS)

    def _check(self):
        if not self._allowed():
            raise AccessError("Tài khoản chưa được cấp quyền hỏi giá nhà cung cấp.")

    def _get_quote(self, quote_id):
        quote = request.env["hlv.vendor.quote"].browse(_to_int(quote_id)).exists()
        if not quote:
            raise UserError("Không tìm thấy yêu cầu báo giá.")
        return quote

    def _scope_domain(self, mine):
        return [("user_id", "=", request.env.uid)] if mine else []

    def _search_domain(self, search):
        search = (search or "").strip()
        if not search:
            return []
        domains = [
            [("name", "ilike", search)],
            [("partner_id", "ilike", search)],
            [("request_id.name", "ilike", search)],
            [("origin", "ilike", search)],
            [("sale_order_id.name", "ilike", search)],
            [("line_ids.product_id", "ilike", search)],
            # Người yêu cầu trên YCMH, dạng "TÊN (MÃ SALE)".
            [("request_id.x_misa_requested_by", "ilike", search)],
        ]
        if has_sale_code(request.env):
            domains += [
                [(f"sale_order_id.{SALE_CODE_FIELD}", "ilike", search)],
                [(f"request_id.sale_order_id.{SALE_CODE_FIELD}", "ilike", search)],
            ]
        return expression.OR(domains)

    def _status_domain(self, status):
        if status in ("waiting", "quoted", "expired"):
            return request.env["hlv.vendor.quote"]._vendor_status_domain(status)
        if status == "all":
            return [("state", "!=", "cancel")]
        return [("state", "=", status)]

    def _line_vals(self, raw_lines, pr):
        """Dòng sale gửi lên → giá trị dòng báo giá. Dòng YCMH lạ (không thuộc YCMH đã chọn) bị bỏ."""
        env = request.env
        vals_list = []
        for index, raw in enumerate(raw_lines, start=1):
            product = env["product.product"].browse(_to_int(raw.get("product_id"))).exists()
            try:
                qty = float(raw.get("qty") or 0)
            except (TypeError, ValueError):
                qty = 0
            if not product or qty <= 0:
                raise UserError(f"Dòng {index}: thiếu sản phẩm hoặc số lượng phải lớn hơn 0.")
            request_line = env["purchase.request.line"].browse(_to_int(raw.get("request_line_id"))).exists()
            if request_line and request_line.request_id != pr:
                request_line = env["purchase.request.line"]
            default_uom = product.uom_po_id or product.uom_id
            uom = env["uom.uom"].browse(_to_int(raw.get("uom_id"))).exists()
            if not uom or uom.category_id != default_uom.category_id:
                uom = default_uom
            vals_list.append({
                "sequence": index,
                "product_id": product.id,
                "name": (raw.get("name") or product.display_name)[:255],
                "product_qty": qty,
                "product_uom_id": uom.id,
                "request_line_id": request_line.id or False,
            })
        return vals_list
