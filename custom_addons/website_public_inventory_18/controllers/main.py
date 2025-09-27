# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import math

PAGE_SIZE = 20


def _get_allowed_warehouses():
    """Warehouses được phép public theo ir.config_parameter.
    Nếu chưa cấu hình thì trả toàn bộ kho."""
    env = request.env
    param_val = env["ir.config_parameter"].sudo().get_param(
        "website_public_inventory_18.allowed_warehouse_ids", default=""
    )
    ids = [int(x) for x in param_val.split(",") if x.strip().isdigit()]
    Wh = env["stock.warehouse"].sudo()
    return Wh.browse(ids).exists() if ids else Wh.search([])


def _domain_for_locations(warehouse_id):
    """Domain theo location: dùng view_location_id (gốc kho) để bao trùm toàn bộ cây nội bộ."""
    env = request.env
    Wh = env["stock.warehouse"].sudo()
    if warehouse_id:
        wh = Wh.browse(int(warehouse_id)).exists()
        if wh:
            return [("location_id", "child_of", wh.view_location_id.id)]
        return [("id", "=", -1)]  # kho không hợp lệ
    # Không chọn kho -> gộp tất cả gốc kho được phép
    allowed = _get_allowed_warehouses()
    if not allowed:
        return [("id", "=", -1)]
    root_ids = allowed.mapped("view_location_id").ids
    return [("location_id", "child_of", root_ids)]


def _as_int_or_none(v):
    try:
        return int(v)
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

        wid = _as_int_or_none(warehouse_id)

        # Domain cơ bản: theo cây location của kho (hoặc các kho cho phép)
        domain = _domain_for_locations(wid)

        # Prefilter: chỉ cần có tồn thực tế > 0 (giữ nhẹ, tránh quét rỗng)
        domain += [("quantity", ">", 0)]

        # Tìm theo từ khóa (name / default_code / barcode) - OR 3 điều kiện
        if q:
            domain += [
                "|",
                "|",
                ("product_id.name", "ilike", q),
                ("product_id.default_code", "ilike", q),
                ("product_id.barcode", "ilike", q),
            ]

        Quant = env["stock.quant"].sudo()

        # Gộp theo product: lấy tồn khả dụng & tồn thực tế
        groups = Quant.read_group(
            domain,
            ["product_id", "available_quantity:sum", "quantity:sum"],
            ["product_id"],
            limit=PAGE_SIZE,
            offset=(page - 1) * PAGE_SIZE,
            orderby="product_id",
        )

        # Tổng nhóm để phân trang
        count_groups = Quant.read_group(domain, ["product_id"], ["product_id"])
        total = len(count_groups)
        pages = max(1, math.ceil(total / PAGE_SIZE)) if total else 1

        # Lấy thông tin sản phẩm
        prod_ids = [g["product_id"][0] for g in groups if g.get("product_id")]
        Product = env["product.product"].sudo()
        pmap = {p.id: p for p in Product.browse(prod_ids)}

        rows = []
        for g in groups:
            if not g.get("product_id"):
                continue
            pid = g["product_id"][0]
            p = pmap.get(pid)
            if not p:
                continue

            avail = g.get("available_quantity_sum") or 0.0
            total_qty = g.get("quantity_sum") or 0.0

            rows.append(
                {
                    "id": pid,
                    "name": p.name,
                    "default_code": (p.default_code or ""),
                    "barcode": (p.barcode or ""),
                    "uom": p.uom_id.name,
                    "qty": avail,              # tồn khả dụng
                    "qty_total": total_qty,    # tồn thực tế (tuỳ chọn hiển thị)
                    "website_url": getattr(p.product_tmpl_id, "website_url", "") or "",
                }
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
        # API JSON cho tìm kiếm tức thời nếu cần
        resp = self.inventory_page(q=q, warehouse_id=warehouse_id, page=page)
        return resp.qcontext.get("rows", [])
