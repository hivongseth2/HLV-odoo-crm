# -*- coding: utf-8 -*-
import logging
import math
from odoo import http
from odoo.http import request

PAGE_SIZE = 20
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

        # Tìm theo từ khóa (OR 3 điều kiện)
        if q:
            domain += [
                "|", "|",
                ("product_id.name", "ilike", q),
                ("product_id.default_code", "ilike", q),
                ("product_id.barcode", "ilike", q),
            ]

        # >>>>>>>>>>>>>  FIX MULTI-COMPANY CONTEXT  <<<<<<<<<<<<<<
        company_ids = _companies_for_context(wid)
        if not company_ids:
            # fallback nhẹ: tất cả company của môi trường (public user thường 1 company)
            company_ids = env.companies.ids

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
        pmap = {p.id: p for p in Product.browse(prod_ids)}

        rows = []
        for g in groups:
            if not g.get("product_id"):
                continue
            pid = g["product_id"][0]
            p = pmap.get(pid)
            if not p:
                continue

            qty = _rg_sum(g, "quantity")
            res = _rg_sum(g, "reserved_quantity")
            avail = qty - res
            # Nếu muốn chặn số âm (tuỳ chọn): avail = max(0.0, qty - res)

            rows.append({
                "id": pid,
                "name": p.name,
                "default_code": p.default_code or "",
                "barcode": p.barcode or "",
                "uom": p.uom_id.name,
                "qty": avail,        # tồn khả dụng
                "qty_total": qty,    # tồn thực tế
                "website_url": getattr(p.product_tmpl_id, "website_url", "") or "",
            })
            _logger.debug(
                "Product %s (%s): qty_total=%.6f, reserved=%.6f, avail=%.6f | raw=%s",
                pid, p.default_code or "-", qty, res, avail, g
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
        # Tận dụng qcontext của trang HTML để tránh lặp code
        resp = self.inventory_page(q=q, warehouse_id=warehouse_id, page=page)
        return resp.qcontext.get("rows", [])
