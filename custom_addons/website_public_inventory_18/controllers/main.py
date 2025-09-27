
# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import math

PAGE_SIZE = 20

def _get_allowed_warehouses():
    """Return warehouses allowed to be public, based on settings (ir.config_parameter).
    If none configured, default to all warehouses.
    """
    env = request.env
    param_val = env["ir.config_parameter"].sudo().get_param(
        "website_public_inventory_18.allowed_warehouse_ids", default=""
    )
    ids = [int(x) for x in param_val.split(",") if x.strip().isdigit()]
    Wh = env["stock.warehouse"].sudo()
    if ids:
        return Wh.browse(ids).exists()
    return Wh.search([])

def _domain_for_locations(warehouse_id):
    env = request.env
    Wh = env["stock.warehouse"].sudo()
    if warehouse_id:
        wh = Wh.browse(int(warehouse_id)).exists()
        if wh:
            return [("location_id", "child_of", wh.lot_stock_id.id)]
        return [("id", "=", -1)]
    # warehouse_id None/"" -> tất cả kho được phép
    allowed = _get_allowed_warehouses()
    if not allowed:
        return [("id", "=", -1)]
    loc_ids = allowed.mapped("lot_stock_id").ids
    return [("location_id", "child_of", loc_ids)]


def _as_int_or_none(v):
    try:
        i = int(v)
        return i
    except (TypeError, ValueError):
        return None

class PublicInventory(http.Controller):
    @http.route(["/search_stock"], type="http", auth="public", website=True, sitemap=True)
    def inventory_page(self, q="", warehouse_id=None, page=1, **kw):
        env = request.env
        try:
            page = int(page or 1)
        except Exception:
            page = 1

        # Base domain: allowed stock locations only, only positive quantity prefilter
        wid = _as_int_or_none(warehouse_id)
        domain = _domain_for_locations(wid) + [("quantity", ">", 0)]
        # Text search (product fields)
        if q:
            # Build a grouped domain: (& base (| cond1 (| cond2 cond3)))
             domain += ['|', '|',
                    ('product_id.name', 'ilike', q),
                    ('product_id.default_code', 'ilike', q),
                    ('product_id.barcode', 'ilike', q),
                ]

        Quant = env["stock.quant"].sudo()

        # Aggregate by product: sum(quantity), sum(reserved_quantity)
        groups = Quant.read_group(
            domain,
            ["product_id", "quantity:sum", "reserved_quantity:sum"],
            ["product_id"],
            limit=PAGE_SIZE,
            offset=(page - 1) * PAGE_SIZE,
            orderby="product_id",
        )

        # Count groups for pagination
        count_groups = Quant.read_group(domain, ["product_id"], ["product_id"])
        total = len(count_groups)
        pages = max(1, math.ceil(total / PAGE_SIZE))

        # Fetch product details
        prod_ids = [g["product_id"][0] for g in groups if g.get("product_id")]
        Product = env["product.product"].sudo()
        prods = Product.browse(prod_ids)
        pmap = {p.id: p for p in prods}

        rows = []
        for g in groups:
            if not g.get("product_id"):
                continue
            pid = g["product_id"][0]
            p = pmap.get(pid)
            if not p:
                continue
            qty = g.get("quantity_sum") or 0.0
            res = g.get("reserved_quantity_sum") or 0.0
            # available = qty - res
            # if available <= 0:
            #     continue
            # rows.append({
            #     "id": pid,
            #     "name": p.name,
            #     "default_code": p.default_code or "",
            #     "barcode": p.barcode or "",
            #     "uom": p.uom_id.name,
            #     "qty": available,
            #     "website_url": getattr(p.product_tmpl_id, "website_url", "") or "",
            # })
            
            available = (g.get("quantity_sum") or 0.0) - (g.get("reserved_quantity_sum") or 0.0)
            rows.append({
                "id": pid,
                "name": p.name,
                "default_code": p.default_code or "",
                "barcode": p.barcode or "",
                "uom": p.uom_id.name,
                # Tuỳ nhu cầu: hiển thị available hoặc tổng quantity
                "qty": available,  # hoặc: g.get("quantity_sum") or 0.0
                "website_url": getattr(p.product_tmpl_id, "website_url", "") or "",
            })

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

    @http.route(["/inventory/json"], type="json", auth="public", methods=["POST"])
    def inventory_json(self, q="", warehouse_id=None, page=1):
        resp = self.inventory_page(q=q, warehouse_id=warehouse_id, page=page)
        return resp.qcontext.get("rows", [])
