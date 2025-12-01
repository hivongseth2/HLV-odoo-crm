# -*- coding: utf-8 -*-
import hmac
import logging
import math
import base64
from odoo import http
from odoo.http import request
from odoo.osv import expression

PAGE_SIZE = 25
_logger = logging.getLogger(__name__)
PW_PARAM_KEY = "website_public_inventory_18.search_password"
SESSION_KEY_OK = "inv_pw_ok"
SESSION_KEY_ERR = "inv_pw_err"

def _get_search_password():
    return request.env["ir.config_parameter"].sudo().get_param(PW_PARAM_KEY, default="") or ""

def _consteq(a, b):
    # so sánh thời gian hằng để tránh lộ timing
    return hmac.compare_digest(str(a or ""), str(b or ""))

def _pw_allowed():
    """Cho phép truy cập nếu:
       - không cấu hình mật khẩu, hoặc
       - đã xác thực ở session hiện tại.
    """
    conf = _get_search_password()
    return not conf or bool(request.session.get(SESSION_KEY_OK))
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
                # ---- GATE: mật khẩu theo session ----
        conf_pw = _get_search_password()
        if conf_pw:  # chỉ gate nếu đã cấu hình mật khẩu
            # nếu chưa pass và vừa POST: kiểm tra
            if not request.session.get(SESSION_KEY_OK):
                if request.httprequest.method == "POST":
                    inp = (request.params.get("inv_password") or "").strip()
                    if _consteq(inp, conf_pw):
                        request.session[SESSION_KEY_OK] = True
                        request.session.pop(SESSION_KEY_ERR, None)
                        # Về lại trang (tránh resubmit), có thể giữ query nếu muốn
                        return request.redirect(request.httprequest.path)
                    else:
                        # Sai mật khẩu: đánh dấu lỗi, KHÔNG hiển thị form nữa => yêu cầu reload
                        request.session[SESSION_KEY_ERR] = True
                        return request.render(
                            "website_public_inventory_18.inventory_page",
                            {"pw_ok": False, "pw_err": True}
                        )
                else:
                    # GET lần đầu: hiện form nhập mật khẩu
                    request.session.pop(SESSION_KEY_ERR, None)
                    return request.render(
                        "website_public_inventory_18.inventory_page",
                        {"pw_ok": False, "pw_err": False}
                    )
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
        domain += [("product_id.active", "=", True)]
        # Tìm theo từ khóa: hỗ trợ nhiều từ khóa, phân cách bởi dấu phẩy
        # Tìm theo từ khóa: hỗ trợ nhiều từ khóa, phân cách bởi dấu phẩy
        if q:
            # 1. Tách các nhóm tìm kiếm bằng dấu phẩy (Logic OR giữa các nhóm)
            search_groups = list({t.strip() for t in q.split(",") if t.strip()})
            final_search_dom = []

            for group in search_groups:
                # 2. Tách từng từ trong nhóm bằng dấu cách (Logic AND giữa các từ)
                # Ví dụ: "fpd3 máy" -> ["fpd3", "máy"] -> Phải chứa cả 2 từ này
                tokens = group.split()
                group_domain = [] 
                
                for token in tokens:
                    # Mỗi từ (token) có thể nằm ở Tên HOẶC Mã HOẶC Barcode
                    token_dom = [
                        '|', '|',
                        ('product_id.name', 'ilike', token),
                        ('product_id.default_code', 'ilike', token),
                        ('product_id.barcode', 'ilike', token),
                    ]
                    # Cộng dồn vào group_domain (Mặc định Odoo nối list là AND)
                    group_domain += token_dom
                
                # 3. Gộp các nhóm lớn bằng OR
                if group_domain:
                    final_search_dom = expression.OR([final_search_dom, group_domain])
            
            domain += final_search_dom

        # >>>>>>>>>>>>>  FIX MULTI-COMPANY CONTEXT  <<<<<<<<<<<<<<
        company_ids = _companies_for_context(wid)
        if not company_ids:
            company_ids = env.companies.ids  # fallback: công ty hiện có

        Quant = env["stock.quant"].sudo().with_context(allowed_company_ids=company_ids)
        Product = env["product.product"].sudo().with_context(allowed_company_ids=company_ids)

        # NEW: đọc tham số checkbox lọc tồn <= 5
        low_stock = request.params.get('low_stock') in ('1', 'true', 'on')

        if low_stock:
            # Lấy tất cả nhóm, sau đó lọc bằng Python theo qty_total <= 5 và loại combo
            groups_all = Quant.read_group(
                domain,
                ["product_id", "quantity:sum", "reserved_quantity:sum"],
                ["product_id"],
                orderby="product_id",
                lazy=False,
            )
            gmap = {g["product_id"][0]: g for g in groups_all if g.get("product_id")}
            prod_ids_all = list(gmap.keys())

            products_all = Product.browse(prod_ids_all)
            pmap_all = {p.id: p for p in products_all}

            filtered_ids = []
            for pid in prod_ids_all:
                p = pmap_all.get(pid)
                if not p:
                    continue
                if getattr(p.product_tmpl_id, "is_combo", False):
                    continue
                qty_total = _rg_sum(gmap[pid], "quantity")
                if qty_total <= 5.0:
                    filtered_ids.append(pid)

            # Phân trang sau lọc
            total = len(filtered_ids)
            pages = max(1, math.ceil(total / PAGE_SIZE)) if total else 1
            start = (page - 1) * PAGE_SIZE
            end = start + PAGE_SIZE
            page_ids = filtered_ids[start:end]

            products = Product.browse(page_ids)
            pmap = {p.id: p for p in products}

            rows = []
            for pid in page_ids:
                p = pmap.get(pid)
                if not p:
                    continue
                g = gmap.get(pid) or {}
                qty_total = _rg_sum(g, "quantity")
                res = _rg_sum(g, "reserved_quantity")

                p_ctx = p.with_context(warehouse=wid) if wid else p
                qty_forecasted = p_ctx.virtual_available

                rows.append({
                    "id": pid,
                    "name": p.name,
                    "default_code": p.default_code or "",
                    "barcode": p.barcode or "",
                    "uom": p.uom_id.name,
                    "qty_forecasted": qty_forecasted,
                    "qty_total": qty_total,
                    "list_price": p.list_price,
                    "commercial_price": getattr(p.product_tmpl_id, "x_studio_gi_bn_thng_mi", 0.0) or 0.0,
                    "standard_price": p.standard_price,
                    "image_url": _get_product_image_url(p),
                    "website_url": getattr(p.product_tmpl_id, "website_url", "") or "",
                    "is_combo": False,
                })
        else:
            # Nhánh mặc định: dùng limit/offset như cũ
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

            prod_ids = [g["product_id"][0] for g in groups if g.get("product_id")]
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

                # Nếu là combo: giữ nguyên render như cũ (tồn '-')
                if getattr(p.product_tmpl_id, "is_combo", False):
                    rows.append({
                        "id": pid,
                        "name": p.name,
                        "default_code": p.default_code or "",
                        "barcode": p.barcode or "",
                        "uom": p.uom_id.name,
                        "qty_forecasted": 0.0,
                        "qty_total": 0.0,
                        "list_price": p.list_price,
                        "commercial_price": getattr(p.product_tmpl_id, "x_studio_gi_bn_thng_mi", 0.0) or 0.0,
                        "standard_price": p.standard_price,
                        "image_url": _get_product_image_url(p),
                        "website_url": getattr(p.product_tmpl_id, "website_url", "") or "",
                        "is_combo": True,
                    })
                    continue

                qty_total = _rg_sum(g, "quantity")
                res = _rg_sum(g, "reserved_quantity")

                p_ctx = p.with_context(warehouse=wid) if wid else p
                qty_forecasted = p_ctx.virtual_available

                rows.append({
                    "id": pid,
                    "name": p.name,
                    "default_code": p.default_code or "",
                    "barcode": p.barcode or "",
                    "uom": p.uom_id.name,
                    "qty_forecasted": qty_forecasted,
                    "qty_total": qty_total,
                    "list_price": p.list_price,
                    "commercial_price": getattr(p.product_tmpl_id, "x_studio_gi_bn_thng_mi", 0.0) or 0.0,
                    "standard_price": p.standard_price,
                    "image_url": _get_product_image_url(p),
                    "website_url": getattr(p.product_tmpl_id, "website_url", "") or "",
                    "is_combo": False,
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
                "pw_ok": True,
            },
        )

    @http.route(["/search_stock/json"], type="json", auth="public", methods=["POST"])
    def inventory_json(self, q="", warehouse_id=None, page=1):
        if not _pw_allowed():
            return {"ok": False, "error": "access_denied", "rows": []}
        resp = self.inventory_page(q=q, warehouse_id=warehouse_id, page=page)
        return resp.qcontext.get("rows", [])
    
    # ========= NEW: Breakdown theo từng kho cho 1 product =========
    @http.route(["/search_stock/product_breakdown"], type="json", auth="public", methods=["POST"])
    def product_breakdown(self, product_id=None, warehouse_id=None, detail_mode=None):
        if not _pw_allowed():
            return {"ok": False, "error": "access_denied", "rows": []}

        env = request.env
        pid = _as_int_or_none(product_id)
        if not pid:
            return {"ok": False, "error": "invalid_product_id", "rows": []}
        
        def _sum_for_product_in_wh(Quant, product_id, warehouse):
            """Trả về (qty_total, qty_reserved) của product trong 1 kho."""
            domain = [
                ("product_id", "=", product_id),
                ("location_id", "child_of", warehouse.view_location_id.id),
            ]
            grps = Quant.read_group(
                domain,
                ["product_id", "quantity:sum", "reserved_quantity:sum"],
                ["product_id"],
                lazy=False,
            )
            if grps:
                g = grps[0]
                qt = _rg_sum(g, "quantity")
                qr = _rg_sum(g, "reserved_quantity")
            else:
                qt = qr = 0.0
            return qt, qr
        # lấy param từ payload JSON-RPC (phòng trường hợp lib gọi khác)
        params = request.jsonrequest.get("params") if hasattr(request, "jsonrequest") else {}
        if params:
            if warehouse_id is None:
                warehouse_id = params.get("warehouse_id")
            if detail_mode is None:
                detail_mode = params.get("detail_mode")

        wid = _as_int_or_none(warehouse_id)

        # Company context như trang chính
        company_ids = _companies_for_context(wid)
        if not company_ids:
            company_ids = env.companies.ids

        Quant = env["stock.quant"].sudo().with_context(allowed_company_ids=company_ids)
        Product = env["product.product"].sudo().with_context(allowed_company_ids=company_ids)
        Warehouse = env["stock.warehouse"].sudo().with_context(allowed_company_ids=company_ids)

        product = Product.browse(pid).exists()
        if not product:
            return {"ok": False, "error": "product_not_found", "rows": []}

        tmpl = product.product_tmpl_id
        is_combo = bool(getattr(tmpl, "is_combo", False))

        # ===== Nếu là combo: components_by_warehouse =====
        if is_combo:
            # Danh sách kho mục tiêu
            if wid:
                wh = Warehouse.browse(wid).exists()
                warehouses = wh if wh else Warehouse.browse([])
            else:
                warehouses = _get_allowed_warehouses()
                if not warehouses:
                    warehouses = Warehouse.search([])

            ComboLine = env["combo.product"].sudo().with_context(allowed_company_ids=company_ids)
            lines = ComboLine.search([("product_template_id", "=", tmpl.id)])

            rows = []
            for line in lines:
                child = line.product_id
                if not child:
                    continue

                wh_rows = []
                for wh in warehouses:
                    qt, qr = _sum_for_product_in_wh(Quant, child.id, wh)
                    wh_rows.append({
                        "warehouse_id": wh.id,
                        "warehouse_name": wh.name,
                        "qty_total": qt,
                        "qty_reserved": qr,
                        "qty_available": qt - qr,
                    })

                rows.append({
                    "child_product_id": child.id,
                    "default_code": child.default_code or "",
                    "name": child.name or "",
                    "uom": child.uom_id.name or "",
                    "component_qty_in_combo": float(line.product_quantity or 1.0),
                    "warehouses": wh_rows,
                })

            return {"ok": True, "mode": "components_by_warehouse", "rows": rows}

        # ===== Sản phẩm thường: breakdown theo kho như cũ =====
        if wid:
            wh = Warehouse.browse(wid).exists()
            warehouses = wh if wh else Warehouse.browse([])
        else:
            warehouses = _get_allowed_warehouses()
            if not warehouses:
                warehouses = Warehouse.search([])

        rows = []
        for wh in warehouses:
            domain = [
                ("product_id", "=", pid),
                ("location_id", "child_of", wh.view_location_id.id),
            ]
            grps = Quant.read_group(
                domain,
                ["product_id", "quantity:sum", "reserved_quantity:sum"],
                ["product_id"],
                lazy=False,
            )
            if grps:
                g = grps[0]
                qty_total = _rg_sum(g, "quantity")
                qty_reserved = _rg_sum(g, "reserved_quantity")
            else:
                qty_total = 0.0
                qty_reserved = 0.0

            rows.append({
                "warehouse_id": wh.id,
                "warehouse_name": wh.name,
                "qty_available": qty_total - qty_reserved,
                "qty_total": qty_total,
                "qty_reserved": qty_reserved,
            })

        return {"ok": True, "mode": "warehouses", "rows": rows}
    
    @http.route(["/search_stock/suggest"], type="json", auth="public", methods=["POST"])
    def search_suggest(self, q=""):
        """Gợi ý tìm kiếm sản phẩm (tối đa 10 kết quả)"""
        if not _pw_allowed():
            return {"ok": False, "error": "access_denied", "products": []}
        
        env = request.env
        q = (q or "").strip()
        
        if not q or len(q) < 2:
            return {"ok": True, "products": []}
        
        # Company context
        company_ids = env.companies.ids
        Product = env["product.product"].sudo().with_context(allowed_company_ids=company_ids)
        
        # Tìm kiếm theo tên, mã, hoặc barcode
        domain = [
            '|', '|',
            ('name', 'ilike', q),
            ('default_code', 'ilike', q),
            ('barcode', 'ilike', q),
        ]
        
        products = Product.search(domain, order='name')
        
        results = []
        for p in products:
            results.append({
                "id": p.id,
                "name": p.name,
                "default_code": p.default_code or "",
                "barcode": p.barcode or "",
                "image_url": _get_product_image_url(p),
            })
        
        return {"ok": True, "products": results}
