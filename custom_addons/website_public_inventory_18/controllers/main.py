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
    return hmac.compare_digest(str(a or ""), str(b or ""))

def _pw_allowed():
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
            return [("location_id", "child_of", wh.view_location_id.id)]
        return [("id", "=", -1)]
    allowed = _get_allowed_warehouses()
    if not allowed:
        return [("id", "=", -1)]
    root_ids = allowed.mapped("view_location_id").ids
    return [("location_id", "child_of", root_ids)]

def _companies_for_context(warehouse_id):
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
    v = row.get(f"{base}_sum")
    if v is None:
        v = row.get(base)
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0

def _get_product_image_url(product):
    if not product:
        return ""
    if product.image_1920:
        return f"/web/image/product.product/{product.id}/image_1920"
    elif product.image_128:
        return f"/web/image/product.product/{product.id}/image_128"
    
    tmpl = product.product_tmpl_id
    if tmpl.image_1920:
        return f"/web/image/product.template/{tmpl.id}/image_1920"
    elif tmpl.image_128:
        return f"/web/image/product.template/{tmpl.id}/image_128"
    return ""

class PublicInventory(http.Controller):
    
    @http.route(["/search_stock"], type="http", auth="public", website=True, sitemap=True)
    def inventory_page(self, q="", warehouse_id=None, page=1, **kw):
        # 1. AUTH & SESSION CHECK
        conf_pw = _get_search_password()
        if conf_pw:
            if not request.session.get(SESSION_KEY_OK):
                if request.httprequest.method == "POST":
                    inp = (request.params.get("inv_password") or "").strip()
                    if _consteq(inp, conf_pw):
                        request.session[SESSION_KEY_OK] = True
                        request.session.pop(SESSION_KEY_ERR, None)
                        return request.redirect(request.httprequest.path)
                    else:
                        request.session[SESSION_KEY_ERR] = True
                        return request.render("website_public_inventory_18.inventory_page", {"pw_ok": False, "pw_err": True})
                else:
                    request.session.pop(SESSION_KEY_ERR, None)
                    return request.render("website_public_inventory_18.inventory_page", {"pw_ok": False, "pw_err": False})

        # 2. PREPARE ENVIRONMENT
        env = request.env
        try:
            page = int(page or 1)
        except Exception:
            page = 1
        
        wid = _as_int_or_none(warehouse_id)
        
        # Domain cơ bản
        domain = _domain_for_locations(wid)
        domain += [("product_id.active", "=", True)] # Chỉ lấy sản phẩm active
        
        # (Optional) Nếu muốn ẩn sản phẩm thường có tồn <= 0 ngay từ SQL
        # domain += [("quantity", ">", 0)] 
        
        # 3. SMART SEARCH DOMAIN
        if q:
            search_groups = [t.strip() for t in q.split(",") if t.strip()]
            domains_per_group = []
            for group in search_groups:
                tokens = group.split()
                domains_per_token = []
                for token in tokens:
                    token_domain = [
                        '|', '|',
                        ('product_id.name', 'ilike', token),
                        ('product_id.default_code', 'ilike', token),
                        ('product_id.barcode', 'ilike', token),
                    ]
                    domains_per_token.append(token_domain)
                if domains_per_token:
                    domains_per_group.append(expression.AND(domains_per_token))
            
            if domains_per_group:
                final_search_dom = expression.OR(domains_per_group)
                domain = expression.AND([domain, final_search_dom])

        # Context Company
        company_ids = _companies_for_context(wid)
        if not company_ids:
            company_ids = env.companies.ids

        Quant = env["stock.quant"].sudo().with_context(allowed_company_ids=company_ids)
        Product = env["product.product"].sudo().with_context(allowed_company_ids=company_ids)
        
        low_stock = request.params.get('low_stock') in ('1', 'true', 'on')

        # 4. DATA FETCHING (Lấy danh sách ID sản phẩm cần hiển thị)
        products_to_display = []
        gmap = {} # Map lưu thông tin tồn kho từ read_group (cho sản phẩm thường)
        
        if low_stock:
            # Nếu lọc tồn thấp: Lấy HẾT về rồi lọc bằng Python (vì combo phải tính mới biết tồn)
            groups_all = Quant.read_group(
                domain,
                ["product_id", "quantity:sum", "reserved_quantity:sum"],
                ["product_id"],
                orderby="product_id",
                lazy=False,
            )
            
            # Map dữ liệu quant
            gmap = {g["product_id"][0]: g for g in groups_all if g.get("product_id")}
            all_pids = list(gmap.keys())
            
            # Lấy recordset product để kiểm tra is_combo
            all_products = Product.browse(all_pids)
            
            filtered_pids = []
            
            # Lọc: Tồn <= 5 (kể cả combo)
            for p in all_products:
                qty_check = 0.0
                is_combo = getattr(p.product_tmpl_id, "is_combo", False)
                
                if is_combo:
                    # Tính sơ bộ tồn combo để lọc (Logic tính lặp lại ở dưới, nhưng cần để filter)
                    # Lưu ý: Hiệu năng có thể chậm nếu nhiều combo. 
                    # Để tối ưu: tách hàm tính tồn combo riêng.
                    qty_check = self._compute_combo_qty(env, p, wid)
                else:
                    qty_check = _rg_sum(gmap.get(p.id, {}), "quantity")
                
                if qty_check <= 5.0:
                    filtered_pids.append(p.id)
            
            # Phân trang Python
            total = len(filtered_pids)
            pages = max(1, math.ceil(total / PAGE_SIZE)) if total else 1
            if page > pages: page = pages
            start = (page - 1) * PAGE_SIZE
            end = start + PAGE_SIZE
            
            page_pids = filtered_pids[start:end]
            products_to_display = Product.browse(page_pids)
            
        else:
            # Chế độ thường: Phân trang bằng SQL read_group
            groups = Quant.read_group(
                domain,
                ["product_id", "quantity:sum", "reserved_quantity:sum"],
                ["product_id"],
                limit=PAGE_SIZE,
                offset=(page - 1) * PAGE_SIZE,
                orderby="product_id",
            )
            
            # Đếm tổng
            count_groups = Quant.read_group(domain, ["product_id"], ["product_id"])
            total = len(count_groups)
            pages = max(1, math.ceil(total / PAGE_SIZE)) if total else 1
            
            # Danh sách ID trang hiện tại
            page_pids = [g["product_id"][0] for g in groups if g.get("product_id")]
            products_to_display = Product.browse(page_pids)
            
            # Map dữ liệu quant cho trang này
            gmap = {g["product_id"][0]: g for g in groups if g.get("product_id")}

        # 5. DATA PROCESSING (Tính toán chi tiết cho từng dòng)
        rows = []
        for p in products_to_display:
            pid = p.id
            is_combo = bool(getattr(p.product_tmpl_id, "is_combo", False))
            
            qty_total = 0.0
            qty_forecasted = 0.0
            
            if is_combo:
                # --- LOGIC COMBO ---
                qty_total = self._compute_combo_qty(env, p, wid)
                qty_forecasted = qty_total # Tạm gán
            else:
                # --- LOGIC THƯỜNG ---
                g = gmap.get(pid, {})
                qty_total = _rg_sum(g, "quantity")
                
                # Dự báo
                p_ctx = p.with_context(warehouse=wid) if wid else p
                qty_forecasted = p_ctx.virtual_available
            
            # Append 1 lần duy nhất -> Không bao giờ duplicate
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
                "is_combo": is_combo,
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

    def _compute_combo_qty(self, env, product, warehouse_id):
        """Hàm phụ trợ tính tồn kho Combo"""
        ComboLines = env['combo.product'].sudo().search([
            ('product_template_id', '=', product.product_tmpl_id.id)
        ])
        
        if not ComboLines:
            return 0.0
            
        possible_sets = []
        for line in ComboLines:
            comp = line.product_id
            if not comp: continue
            
            # Context kho
            if warehouse_id:
                comp_ctx = comp.with_context(warehouse=warehouse_id, location=False)
            else:
                comp_ctx = comp.with_context(warehouse=False, location=False)
                
            hand_qty = comp_ctx.qty_available
            needed_qty = line.product_quantity or 1.0
            
            if needed_qty > 0:
                sets = int(hand_qty // needed_qty)
                possible_sets.append(sets)
            else:
                possible_sets.append(999999)
        
        if possible_sets:
            return float(max(0, min(possible_sets)))
        return 0.0

    @http.route(["/search_stock/json"], type="json", auth="public", methods=["POST"])
    def inventory_json(self, q="", warehouse_id=None, page=1):
        if not _pw_allowed():
            return {"ok": False, "error": "access_denied", "rows": []}
        resp = self.inventory_page(q=q, warehouse_id=warehouse_id, page=page)
        return resp.qcontext.get("rows", [])
    
    # ========= API CHI TIẾT (Giữ nguyên logic cũ của bạn) =========
    @http.route(["/search_stock/product_breakdown"], type="json", auth="public", methods=["POST"])
    def product_breakdown(self, product_id=None, warehouse_id=None, detail_mode=None):
        if not _pw_allowed():
            return {"ok": False, "error": "access_denied", "rows": []}

        env = request.env
        pid = _as_int_or_none(product_id)
        if not pid:
            return {"ok": False, "error": "invalid_product_id", "rows": []}
        
        def _sum_for_product_in_wh(Quant, product_id, warehouse):
            domain = [
                ("product_id", "=", product_id),
                ("location_id", "child_of", warehouse.view_location_id.id),
            ]
            grps = Quant.read_group(domain, ["product_id", "quantity:sum", "reserved_quantity:sum"], ["product_id"], lazy=False)
            if grps:
                g = grps[0]
                qt = _rg_sum(g, "quantity")
                qr = _rg_sum(g, "reserved_quantity")
            else:
                qt = qr = 0.0
            return qt, qr

        params = request.jsonrequest.get("params") if hasattr(request, "jsonrequest") else {}
        if params:
            if warehouse_id is None: warehouse_id = params.get("warehouse_id")
            if detail_mode is None: detail_mode = params.get("detail_mode")

        wid = _as_int_or_none(warehouse_id)
        company_ids = _companies_for_context(wid)
        if not company_ids: company_ids = env.companies.ids

        Quant = env["stock.quant"].sudo().with_context(allowed_company_ids=company_ids)
        Product = env["product.product"].sudo().with_context(allowed_company_ids=company_ids)
        Warehouse = env["stock.warehouse"].sudo().with_context(allowed_company_ids=company_ids)

        product = Product.browse(pid).exists()
        if not product or not product.active:
            return {"ok": False, "error": "product_not_found", "rows": []}

        tmpl = product.product_tmpl_id
        is_combo = bool(getattr(tmpl, "is_combo", False))

        # 1. COMBO DETAIL
        if is_combo:
            if wid:
                wh = Warehouse.browse(wid).exists()
                warehouses = wh if wh else Warehouse.browse([])
            else:
                warehouses = _get_allowed_warehouses()
                if not warehouses: warehouses = Warehouse.search([])

            ComboLine = env["combo.product"].sudo().with_context(allowed_company_ids=company_ids)
            lines = ComboLine.search([("product_template_id", "=", tmpl.id)])

            rows = []
            for line in lines:
                child = line.product_id
                if not child: continue
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

        # 2. STANDARD PRODUCT DETAIL
        if wid:
            wh = Warehouse.browse(wid).exists()
            warehouses = wh if wh else Warehouse.browse([])
        else:
            warehouses = _get_allowed_warehouses()
            if not warehouses: warehouses = Warehouse.search([])

        rows = []
        for wh in warehouses:
            qt, qr = _sum_for_product_in_wh(Quant, pid, wh)
            rows.append({
                "warehouse_id": wh.id,
                "warehouse_name": wh.name,
                "qty_available": qt - qr,
                "qty_total": qt,
                "qty_reserved": qr,
            })
        return {"ok": True, "mode": "warehouses", "rows": rows}
    
    @http.route(["/search_stock/suggest"], type="json", auth="public", methods=["POST"])
    def search_suggest(self, q=""):
        if not _pw_allowed():
            return {"ok": False, "error": "access_denied", "products": []}
        
        env = request.env
        q = (q or "").strip()
        if not q or len(q) < 2:
            return {"ok": True, "products": []}
        
        company_ids = env.companies.ids
        Product = env["product.product"].sudo().with_context(allowed_company_ids=company_ids)
        
        base_domain = [('active', '=', True)]
        tokens = q.split()
        domains_per_token = []
        
        for token in tokens:
            token_domain = [
                '|', '|',
                ('name', 'ilike', token),
                ('default_code', 'ilike', token),
                ('barcode', 'ilike', token),
            ]
            domains_per_token.append(token_domain)
        
        if domains_per_token:
            search_domain = expression.AND(domains_per_token)
            final_domain = expression.AND([base_domain, search_domain])
        else:
            final_domain = base_domain

        products = Product.search(final_domain, limit=10, order='name')
        
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