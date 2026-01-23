# -*- coding: utf-8 -*-
import hmac
import logging
import math
import base64
from odoo import http
from odoo.http import request
from odoo.osv import expression
from odoo.tools.mimetypes import guess_mimetype

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

# --- CẬP NHẬT: Trả về ảnh mặc định nếu thiếu ---
def _get_product_image_url(product):
    if not product:
        return "/web/static/img/placeholder.png"
    
    # Kiểm tra xem sản phẩm có ảnh không (dựa trên field check nhanh của Odoo)
    # Lưu ý: product.image_128 là binary, check bool(image_128) sẽ chậm nếu load nhiều.
    # Nên dùng route image custom của mình ở dưới, trong đó sẽ handle việc fallback.
    return f"/search_stock/image/{product.id}"

# --- CẬP NHẬT: Helper check combo qua BoM Kit ---
def _is_combo_product(env, product_tmpl_id):
    # Check if this product template has any active phantom BoM (Kit)
    if not product_tmpl_id: return False
    
    # 1. Check field is_combo (backward compatibility/fast check)
    if 'is_combo' in env['product.template']._fields:
        if product_tmpl_id.is_combo: return True
        
    # 2. Check BoM Kit
    # Cache optimization could be needed here but for now direct search
    count = env['mrp.bom'].sudo().search_count([
        ('product_tmpl_id', '=', product_tmpl_id.id),
        ('active', '=', True),
        ('type', '=', 'phantom')
    ])
    return count > 0

class PublicInventory(http.Controller):

    
    # --- CẬP NHẬT: Route ảnh có fallback mặc định ---
    @http.route(["/search_stock/image/<int:product_id>"], type="http", auth="public")
    def stock_image(self, product_id):
        if not _pw_allowed():
            return request.not_found()
        
        record = request.env['product.product'].sudo().browse(product_id).exists()
        
        # Nếu không có record hoặc không có ảnh -> Trả về placeholder mặc định của Odoo
        if not record or not record.image_128:
            return request.redirect('/web/static/img/placeholder.png')

        image_base64 = record.image_128
        image_data = base64.b64decode(image_base64)
        mimetype = guess_mimetype(image_data)
        headers = [('Content-Type', mimetype), ('Cache-Control', 'public, max-age=604800')]
        return request.make_response(image_data, headers)

    @http.route(["/search_stock"], type="http", auth="public", website=True, sitemap=True)
    def inventory_page(self, q="", warehouse_id=None, page=1, **kw):
        # 1. AUTH
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

        # 2. PREPARE
        env = request.env
        try: page = int(page or 1)
        except: page = 1
        
        wid = _as_int_or_none(warehouse_id)
        company_ids = _companies_for_context(wid)
        if not company_ids: company_ids = env.companies.ids

        Quant = env["stock.quant"].sudo().with_context(allowed_company_ids=company_ids)
        Product = env["product.product"].sudo().with_context(allowed_company_ids=company_ids)
        
        low_stock_mode = request.params.get('low_stock') in ('1', 'true', 'on')
        combo_search_mode = request.params.get('combo_search') in ('1', 'true', 'on')

        # 3. DOMAIN
        domain = [("active", "=", True)]
        
        # --- CẬP NHẬT: Lọc Combo (BoM Kit) nếu không check ---
        if not combo_search_mode:
            # Tìm tất cả sản phẩm là Kit
            # Lưu ý: Search này có thể nặng nếu nhiều Kit, nhưng cần thiết để filter
            # Tối ưu: Nếu có field is_combo dùng field thì nhanh hơn, nhưng user yêu cầu bỏ.
            # Dùng subquery domain
            domain.append(('product_tmpl_id.bom_ids.type', '!=', 'phantom')) 
            # Note: bom_ids là One2many, operator != phantom có thể không hoạt động như mong đợi (nó loại nếu MỌI bom != phantom?)
            # Odoo search One2many != value thường có nghĩa "không có dòng nào = value" -> Chính xác là cái ta cần?
            # Test: Product A has 1 BoM (phantom). A.bom_ids.type != phantom returns False?
            # Product B has no BoM. B.bom_ids.type != phantom returns True? (Empty set logic)
            # Safe logic: exclude IDs
            # kit_boms = env['mrp.bom'].sudo().search([('type', '=', 'phantom'), ('active', '=', True)])
            # kit_tmpl_ids = kit_boms.mapped('product_tmpl_id').ids
            # if kit_tmpl_ids:
            #     domain.append(('product_tmpl_id', 'not in', kit_tmpl_ids))
            
            # Sử dụng cách NOT IN cho an toàn
            kit_boms = env['mrp.bom'].sudo().search([('type', '=', 'phantom'), ('active', '=', True)])
            kit_tmpl_ids = kit_boms.mapped('product_tmpl_id').ids
            if kit_tmpl_ids:
                domain.append(('product_tmpl_id', 'not in', kit_tmpl_ids))

        if q:
            search_groups = [t.strip() for t in q.split(",") if t.strip()]
            domains_per_group = []
            for group in search_groups:
                tokens = group.split()
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
                    domains_per_group.append(expression.AND(domains_per_token))
            if domains_per_group:
                final_search_dom = expression.OR(domains_per_group)
                domain = expression.AND([domain, final_search_dom])

        # 4. SEARCH
        found_products = Product.search(domain, order="name asc") 
        final_product_ids = set()
        
        # Pre-fetch BoM status for found products to avoid N+1 queries loop
        # Map tmpl_id -> is_combo
        found_tmpl_ids = found_products.mapped('product_tmpl_id').ids
        # Find which of these are combos
        boms = env['mrp.bom'].sudo().search([
            ('product_tmpl_id', 'in', found_tmpl_ids),
            ('type', '=', 'phantom'), 
            ('active', '=', True)
        ])
        combo_tmpl_ids = set(boms.mapped('product_tmpl_id').ids)

        for p in found_products:
            final_product_ids.add(p.id)
            if combo_search_mode:
                is_combo = p.product_tmpl_id.id in combo_tmpl_ids
                # Nếu là combo (và đang bật search combo), bung children (nếu cần show con)
                # Logic cũ bung con từ combo.product. Logic mới lấy từ BoM.
                if is_combo:
                    # Find children for this specific product
                    # Optimized: filter boms in memory
                    product_bom = next((b for b in boms if b.product_tmpl_id.id == p.product_tmpl_id.id), None)
                    if product_bom:
                         child_ids = product_bom.bom_line_ids.mapped('product_id').ids
                         final_product_ids.update(child_ids)

        sorted_pids = sorted(list(final_product_ids))
        
        # 5. PAGINATION
        total = len(sorted_pids)
        pages = max(1, math.ceil(total / PAGE_SIZE)) if total else 1
        if page > pages: page = pages
        start = (page - 1) * PAGE_SIZE
        end = start + PAGE_SIZE
        
        page_pids = sorted_pids[start:end]
        products_to_display = Product.browse(page_pids)

        quant_domain = [
            ("product_id", "in", page_pids),
            ("location_id.usage", "=", "internal")
        ]
        if wid:
            wh = env['stock.warehouse'].sudo().browse(wid)
            if wh: quant_domain.append(("location_id", "child_of", wh.view_location_id.id))
            else: quant_domain.append(("id", "=", -1))
        else:
             allowed_whs = _get_allowed_warehouses()
             if allowed_whs: quant_domain.append(("location_id", "child_of", allowed_whs.mapped('view_location_id').ids))

        quant_groups = Quant.read_group(quant_domain, ["product_id", "quantity:sum"], ["product_id"], lazy=False)
        qty_map = {g["product_id"][0]: _rg_sum(g, "quantity") for g in quant_groups if g.get("product_id")}

        # Check combos for current page products
        # We need to re-check combo status for page_pids (some might be children added above)
        page_tmpl_ids = products_to_display.mapped('product_tmpl_id').ids
        page_boms = env['mrp.bom'].sudo().search([
            ('product_tmpl_id', 'in', page_tmpl_ids),
            ('type', '=', 'phantom'), 
            ('active', '=', True)
        ])
        page_combo_tmpl_ids = set(page_boms.mapped('product_tmpl_id').ids)

        # 6. BUILD ROWS
        rows = []
        for p in products_to_display:
            pid = p.id
            is_combo = p.product_tmpl_id.id in page_combo_tmpl_ids
            qty_total = 0.0
            
            if is_combo: qty_total = self._compute_combo_qty(env, p, wid)
            else: qty_total = qty_map.get(pid, 0.0)
            
            if low_stock_mode and qty_total > 5.0: continue

            qty_forecasted = 0.0
            if not is_combo:
                p_ctx = p.with_context(warehouse=wid) if wid else p
                qty_forecasted = p_ctx.virtual_available
            else: qty_forecasted = qty_total

            rows.append({
                "id": pid,
                "name": p.name,
                "default_code": p.default_code or "",
                "barcode": p.barcode or "",
                "uom": p.uom_id.name,
                "qty_forecasted": qty_forecasted,
                "qty_total": qty_total, 
                "list_price": p.list_price,
                "price_web": getattr(p.product_tmpl_id, "x_studio_ga_web", 0.0) or 0.0,
                "price_tmdt": getattr(p.product_tmpl_id, "x_studio_gia_san_tmdt", 0.0) or 0.0,
                "price_listed": getattr(p.product_tmpl_id, "x_studio_ga_hng_nim_yt", 0.0) or 0.0,
                "commercial_price": getattr(p.product_tmpl_id, "x_studio_gi_bn_thng_mi", 0.0) or 0.0,
                "standard_price": p.standard_price,
                "image_url": _get_product_image_url(p),
                "website_url": getattr(p.product_tmpl_id, "website_url", "") or "",
                "is_combo": is_combo,
            })

        return request.render(
            "website_public_inventory_18.inventory_page",
            {
                "q": q or "",
                "warehouse_id": wid,
                "warehouses": _get_allowed_warehouses(),
                "rows": rows,
                "page": page,
                "pages": pages,
                "total": total,
                "pw_ok": True,
            },
        )

    # ... (Keep _compute_combo_qty and others) ...
    def _compute_combo_qty(self, env, product, warehouse_id):
        # ... existing improved logic ...
        ComboLines = []
        if hasattr(env, 'combo.product'):
            ComboLines = env['combo.product'].sudo().search([('product_template_id', '=', product.product_tmpl_id.id)])
        
        if not ComboLines:
            bom = env['mrp.bom'].sudo().search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id),
                ('active', '=', True),
                ('type', '=', 'phantom')
            ], limit=1)
            if bom:
                ComboLines = bom.bom_line_ids

        if not ComboLines: return 0.0
        
        possible_sets = []
        for line in ComboLines:
            comp = line.product_id
            if not comp: continue
            
            if warehouse_id: comp_ctx = comp.with_context(warehouse=warehouse_id, location=False)
            else: comp_ctx = comp.with_context(warehouse=False, location=False)
            
            hand_qty = comp_ctx.qty_available
            needed_qty = getattr(line, 'product_quantity', 0) or getattr(line, 'product_qty', 1.0)
            
            if needed_qty > 0: possible_sets.append(int(hand_qty // needed_qty))
            else: possible_sets.append(999999)
            
        return float(max(0, min(possible_sets))) if possible_sets else 0.0

    @http.route(["/search_stock/json"], type="json", auth="public", methods=["POST"])
    def inventory_json(self, q="", warehouse_id=None, page=1):
        if not _pw_allowed(): return {"ok": False, "error": "access_denied", "rows": []}
        resp = self.inventory_page(q=q, warehouse_id=warehouse_id, page=page)
        return resp.qcontext.get("rows", [])
    
    @http.route(["/search_stock/product_breakdown"], type="json", auth="public", methods=["POST"])
    def product_breakdown(self, product_id=None, warehouse_id=None, detail_mode=None):
        if not _pw_allowed(): return {"ok": False, "error": "access_denied", "rows": []}
        env = request.env
        pid = _as_int_or_none(product_id)
        if not pid: return {"ok": False, "error": "invalid_product_id", "rows": []}
        
        # ... helper ...
        def _sum_for_product_in_wh(Quant, product_id, warehouse):
            domain = [("product_id", "=", product_id), ("location_id", "child_of", warehouse.view_location_id.id), ("location_id.usage", "=", "internal")]
            grps = Quant.read_group(domain, ["product_id", "quantity:sum", "reserved_quantity:sum"], ["product_id"], lazy=False)
            if grps:
                g = grps[0]
                return _rg_sum(g, "quantity"), _rg_sum(g, "reserved_quantity")
            return 0.0, 0.0

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
        if not product: return {"ok": False, "error": "product_not_found", "rows": []}
        
        tmpl = product.product_tmpl_id
        # Check BoM
        is_combo = _is_combo_product(env, tmpl)

        if is_combo:
            if wid: wh = Warehouse.browse(wid).exists(); warehouses = wh if wh else Warehouse.browse([])
            else: warehouses = _get_allowed_warehouses() or Warehouse.search([])
            
            lines = []
            if hasattr(env, 'combo.product'):
                ComboLine = env["combo.product"].sudo().with_context(allowed_company_ids=company_ids)
                lines = ComboLine.search([("product_template_id", "=", tmpl.id)])
            
            if not lines:
                 bom = env['mrp.bom'].sudo().search([
                    ('product_tmpl_id', '=', tmpl.id),
                    ('active', '=', True),
                    ('type', '=', 'phantom')
                ], limit=1)
                 if bom:
                     lines = bom.bom_line_ids
            
            rows = []
            for line in lines:
                child = line.product_id
                if not child: continue
                wh_rows = []
                for wh in warehouses:
                    qt, qr = _sum_for_product_in_wh(Quant, child.id, wh)
                    wh_rows.append({"warehouse_id": wh.id, "warehouse_name": wh.name, "qty_total": qt, "qty_reserved": qr, "qty_available": qt - qr})
                rows.append({
                    "child_product_id": child.id, "default_code": child.default_code or "", "name": child.name or "", "uom": child.uom_id.name or "",
                    "image_url": _get_product_image_url(child),
                    "component_qty_in_combo": float(getattr(line, 'product_quantity', 0) or getattr(line, 'product_qty', 1.0)), "warehouses": wh_rows
                })
            return {"ok": True, "mode": "components_by_warehouse", "rows": rows}

        if wid: wh = Warehouse.browse(wid).exists(); warehouses = wh if wh else Warehouse.browse([])
        else: warehouses = _get_allowed_warehouses() or Warehouse.search([])
        rows = []
        for wh in warehouses:
            qt, qr = _sum_for_product_in_wh(Quant, pid, wh)
            rows.append({"warehouse_id": wh.id, "warehouse_name": wh.name, "qty_available": qt - qr, "qty_total": qt, "qty_reserved": qr})
        return {"ok": True, "mode": "warehouses", "rows": rows}
    
    @http.route(["/search_stock/suggest"], type="json", auth="public", methods=["POST"])
    def search_suggest(self, q="", combo_search=False):
        if not _pw_allowed(): return {"ok": False, "error": "access_denied", "products": []}
        env = request.env
        q = (q or "").strip()
        if not q or len(q) < 2: return {"ok": True, "products": []}
        
        company_ids = env.companies.ids
        Product = env["product.product"].sudo().with_context(allowed_company_ids=company_ids)
        Quant = env["stock.quant"].sudo().with_context(allowed_company_ids=company_ids)
        
        domain = [('active', '=', True)]
        # Nếu không tick tìm combo -> Lọc bỏ combo (BoM Kit)
        if not combo_search:
            kit_boms = env['mrp.bom'].sudo().search([('type', '=', 'phantom'), ('active', '=', True)])
            kit_tmpl_ids = kit_boms.mapped('product_tmpl_id').ids
            if kit_tmpl_ids:
                domain.append(('product_tmpl_id', 'not in', kit_tmpl_ids))

        tokens = q.split()
        domains_per_token = []
        for token in tokens:
            domains_per_token.append(['|', '|', ('name', 'ilike', token), ('default_code', 'ilike', token), ('barcode', 'ilike', token)])
        
        if domains_per_token: domain = expression.AND([domain, expression.AND(domains_per_token)])
        
        products = Product.search(domain, limit=10, order='name')
        
        # Tính toán tồn kho
        pids = products.ids
        quant_domain = [("product_id", "in", pids), ("location_id.usage", "=", "internal")]
        allowed_whs = _get_allowed_warehouses()
        if allowed_whs:
            quant_domain.append(("location_id", "child_of", allowed_whs.mapped('view_location_id').ids))
        
        quant_groups = Quant.read_group(quant_domain, ["product_id", "quantity:sum"], ["product_id"], lazy=False)
        qty_map = {g["product_id"][0]: _rg_sum(g, "quantity") for g in quant_groups if g.get("product_id")}

        # Check combos for suggestions
        prod_tmpl_ids = products.mapped('product_tmpl_id').ids
        prod_boms = env['mrp.bom'].sudo().search([
            ('product_tmpl_id', 'in', prod_tmpl_ids),
            ('type', '=', 'phantom'), 
            ('active', '=', True)
        ])
        combo_tmpl_ids = set(prod_boms.mapped('product_tmpl_id').ids)

        results = []
        for p in products:
            is_combo = p.product_tmpl_id.id in combo_tmpl_ids
            qty_total = 0.0
            if is_combo:
                qty_total = self._compute_combo_qty(env, p, None)
            else:
                qty_total = qty_map.get(p.id, 0.0)

            results.append({
                "id": p.id, 
                "name": p.name, 
                "default_code": p.default_code or "", 
                "barcode": p.barcode or "",
                "image_url": _get_product_image_url(p),
                "qty_total": qty_total,
                "is_combo": is_combo,
            })
        
        results.sort(key=lambda x: x['qty_total'], reverse=True)
        return {"ok": True, "products": results}