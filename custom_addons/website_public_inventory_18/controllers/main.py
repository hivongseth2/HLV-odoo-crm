# -*- coding: utf-8 -*-
import logging
import math
import base64
from odoo import http
from odoo.http import request
from odoo.osv import expression

PAGE_SIZE = 25
_logger = logging.getLogger(__name__)


def _get_allowed_warehouses():
    env = request.env
    param_val = env["ir.config_parameter"].sudo().get_param(
        "website_public_inventory_18.allowed_warehouse_ids", default=""
    )
    ids = [int(x) for x in param_val.split(",") if x.strip().isdigit()]
    Wh = env["stock.warehouse"].sudo()
    return Wh.browse(ids).exists() if ids else Wh.search([])


def _domain_for_locations(warehouse_id):
    env = request.env
    Wh = env["stock.warehouse"].sudo()
    if warehouse_id:
        wh = Wh.browse(int(warehouse_id)).exists()
        if wh:
            # Bao trùm toàn bộ cây location nội bộ của kho
            return [("location_id", "child_of", wh.view_location_id.id)]
        return [("id", "=", -1)]
    allowed = _get_allowed_warehouses()
    if not allowed:
        return [("id", "=", -1)]
    root_ids = allowed.mapped("view_location_id").ids
    return [("location_id", "child_of", root_ids)]


def _companies_for_context(warehouse_id):
    """Lấy danh sách company cần cho allowed_company_ids"""
    env = request.env
    Wh = env["stock.warehouse"].sudo()
    if warehouse_id:
        wh = Wh.browse(int(warehouse_id)).exists()
        return wh.company_id.ids if wh else []
    allowed = _get_allowed_warehouses()
    return allowed.mapped("company_id").ids


def _as_int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _rg_sum(row, base):
    """
    Lấy tổng từ read_group:
    - Ưu tiên key f"{base}_sum" (khi dùng 'field:sum' trong fields)
    - Fallback sang key gốc 'base' nếu module/phiên bản trả khác
    """
    v = row.get(f"{base}_sum")
    if v is None:
        v = row.get(base)
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def _get_product_image_url(product):
    """Lấy URL hình ảnh sản phẩm"""
    if not product:
        return ""
    
    # Ưu tiên image_1920, nếu không có thì dùng image_128
    if product.image_1920:
        return f"/web/image/product.product/{product.id}/image_1920"
    elif product.image_128:
        return f"/web/image/product.product/{product.id}/image_128"
    
    # Fallback sang template image
    tmpl = product.product_tmpl_id
    if tmpl.image_1920:
        return f"/web/image/product.template/{tmpl.id}/image_1920"
    elif tmpl.image_128:
        return f"/web/image/product.template/{tmpl.id}/image_128"
    
    return ""


class PublicInventory(http.Controller):
    @http.route(["/search_stock"], type="http", auth="public", website=True, sitemap=True)
    def inventory_page(self, q="", warehouse_id=None, page=1, **kw):
        env = request.env
        try:
            page = int(page or 1)
        except Exception:
            page = 1

        wid = _as_int_or_none(warehouse_id)

        # Domain theo location của kho (hoặc các kho cho phép)
        domain = _domain_for_locations(wid)
        # Prefilter có tồn thực tế > 0 để tránh rỗng
        domain += [("quantity", ">", 0)]

        # Tìm theo từ khóa: hỗ trợ nhiều từ khóa, phân cách bởi dấu phẩy
        if q:
            # tách theo dấu phẩy, loại rỗng, bỏ trùng
            terms = list({t.strip() for t in q.split(",") if t.strip()})
            search_dom = []
            for t in terms:
                # với mỗi term: OR 3 field
                term_dom = [
                    '|', '|',
                    ('product_id.name', 'ilike', t),
                    ('product_id.default_code', 'ilike', t),
                    ('product_id.barcode', 'ilike', t),
                ]
                search_dom = term_dom if not search_dom else expression.OR([search_dom, term_dom])
            domain += search_dom

        # >>>>>>>>>>>>>  FIX MULTI-COMPANY CONTEXT  <<<<<<<<<<<<<<
        company_ids = _companies_for_context(wid)
        if not company_ids:
            company_ids = env.companies.ids  # fallback: công ty hiện có

        Quant = env["stock.quant"].sudo().with_context(allowed_company_ids=company_ids)

        # Gộp theo product: sum(quantity) & sum(reserved_quantity)
        groups = Quant.read_group(
            domain,
            ["product_id", "quantity:sum", "reserved_quantity:sum"],
            ["product_id"],
            limit=PAGE_SIZE,
            offset=(page - 1) * PAGE_SIZE,
            orderby="product_id",
        )
        _logger.debug("read_group returned %d groups", len(groups))

        # Đếm nhóm để phân trang
        count_groups = Quant.read_group(domain, ["product_id"], ["product_id"])
        total = len(count_groups)
        pages = max(1, math.ceil(total / PAGE_SIZE)) if total else 1

        # Lấy thông tin sản phẩm
        prod_ids = [g["product_id"][0] for g in groups if g.get("product_id")]
        Product = env["product.product"].sudo().with_context(allowed_company_ids=company_ids)
        products = Product.browse(prod_ids)
        pmap = {p.id: p for p in products}

        rows = []
        for g in groups:
            if not g.get("product_id"):
                continue
            pid = g["product_id"][0]
            p = pmap.get(pid)
            if not p:
                continue

            qty_total = _rg_sum(g, "quantity")  # Tồn thực tế (qty_on_hand)
            res = _rg_sum(g, "reserved_quantity")
            
            # Tính "Được dự báo" = virtual_available
            # virtual_available = qty_on_hand - outgoing + incoming
            # Nhưng để đơn giản, ta dùng computed field từ product
            # Cần with_context để tính theo kho cụ thể
            if wid:
                p_ctx = p.with_context(warehouse=wid)
            else:
                # Nếu không chọn kho, lấy tổng
                p_ctx = p
            
            qty_forecasted = p_ctx.virtual_available  # Được dự báo

            rows.append({
                "id": pid,
                "name": p.name,
                "default_code": p.default_code or "",
                "barcode": p.barcode or "",
                "uom": p.uom_id.name,
                "qty_forecasted": qty_forecasted,  # Được dự báo (virtual_available)
                "qty_total": qty_total,            # Tồn thực tế (qty_on_hand)
                "list_price": p.list_price,        # Giá bán
                "commercial_price": getattr(p.product_tmpl_id, "x_studio_gi_bn_thng_mi", 0.0) or 0.0,
                "image_url": _get_product_image_url(p),  # URL hình ảnh
                "website_url": getattr(p.product_tmpl_id, "website_url", "") or "",
            })

            _logger.debug(
                "Product %s (%s): qty_total=%.6f, reserved=%.6f, forecasted=%.6f | raw=%s",
                pid, p.default_code or "-", qty_total, res, qty_forecasted, g
            )

        Warehouses = _get_allowed_warehouses()

        return request.render(
            "website_public_inventory_18.inventory_page",
            {
                "q": q or "",
                "warehouse_id": wid,
                "warehouses": Warehouses,
                "rows": rows,
                "page": page,
                "pages": pages,
                "total": total,
            },
        )

    @http.route(["/search_stock/json"], type="json", auth="public", methods=["POST"])
    def inventory_json(self, q="", warehouse_id=None, page=1):
        resp = self.inventory_page(q=q, warehouse_id=warehouse_id, page=page)
        return resp.qcontext.get("rows", [])

    # ========= NEW: Breakdown theo từng kho cho 1 product =========
    @http.route(["/search_stock/product_breakdown"], type="json", auth="public", methods=["POST"])
    def product_breakdown(self, product_id=None, warehouse_id=None):
        """
        Trả về danh sách tồn của product theo từng kho user được phép xem.
        Nếu truyền warehouse_id: chỉ breakdown trong kho đó.
        """
        env = request.env
        pid = _as_int_or_none(product_id)
        if not pid:
            return {"ok": False, "error": "invalid_product_id", "rows": []}

        # Company context như trang chính
        wid = _as_int_or_none(warehouse_id)
        company_ids = _companies_for_context(wid)
        if not company_ids:
            company_ids = env.companies.ids
        Quant = env["stock.quant"].sudo().with_context(allowed_company_ids=company_ids)
        Product = env["product.product"].sudo().with_context(allowed_company_ids=company_ids)

        # Lấy product để tính virtual_available
        product = Product.browse(pid).exists()
        if not product:
            return {"ok": False, "error": "product_not_found", "rows": []}

        # Chọn danh sách kho
        warehouses = []
        if wid:
            wh = env["stock.warehouse"].sudo().browse(wid).exists()
            if wh:
                warehouses = wh
        if not warehouses:
            warehouses = _get_allowed_warehouses()

        rows = []
        for wh in warehouses:
            domain = [
                ("product_id", "=", pid),
                ("location_id", "child_of", wh.view_location_id.id),
            ]
            # nhóm toàn bộ theo product_id (chỉ 1)
            grps = Quant.read_group(
                domain,
                ["product_id", "quantity:sum", "reserved_quantity:sum"],
                ["product_id"],
            )
            if grps:
                g = grps[0]
                qty_total = _rg_sum(g, "quantity")
                qty_reserved = _rg_sum(g, "reserved_quantity")
            else:
                qty_total = qty_reserved = 0.0

            # Tồn khả dụng = Tồn thực tế - Đã giữ hàng
            qty_available = qty_total - qty_reserved

            rows.append({
                "warehouse_id": wh.id,
                "warehouse_name": wh.name,
                "qty_available": qty_available,   # Tồn khả dụng
                "qty_total": qty_total,           # Tồn thực tế
                "qty_reserved": qty_reserved,     # Đã giữ hàng
            })
            _logger.debug(
                "Breakdown pid=%s @WH %s: total=%.6f, reserved=%.6f, available=%.6f",
                pid, wh.name, qty_total, qty_reserved, qty_available
            )

        return {"ok": True, "rows": rows}