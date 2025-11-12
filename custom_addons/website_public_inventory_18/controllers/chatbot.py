# -*- coding: utf-8 -*-
import json
import re
import logging
from collections import defaultdict

from odoo import http
from odoo.http import request
from odoo.osv import expression

_logger = logging.getLogger(__name__)


# -----------------------------
# Utils (normalize & text)
# -----------------------------
def _norm(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _strip_seps(s: str) -> str:
    """Remove spaces and separators for fuzzy compare."""
    return re.sub(r"[\s\-\_\/\.]+", "", s or "")


# -----------------------------
# Controller
# -----------------------------
class ChatbotController(http.Controller):
    # ===== CONFIG =====
    def _get_chatbot_config(self):
        """Read settings from System Parameters."""
        param = request.env["ir.config_parameter"].sudo()
        return {
            "enabled": param.get_param("website_public_inventory_18.chatbot_enabled", default=False) in (True, "True", "1", "true"),
            "api_key": param.get_param("website_public_inventory_18.openai_api_key", default=""),
            "model": param.get_param("website_public_inventory_18.openai_model", default="gpt-4o-mini"),
            "max_tokens": int(param.get_param("website_public_inventory_18.chatbot_max_tokens", default=600)),
            "temperature": float(param.get_param("website_public_inventory_18.chatbot_temperature", default=0.2)),
            "web_search_enabled": param.get_param("website_public_inventory_18.web_search_enabled", default=True) in (True, "True", "1", "true"),
            # kho cho phép hiển thị (tùy chọn)
            "allowed_warehouse_ids": param.get_param("website_public_inventory_18.allowed_warehouse_ids", default=""),
        }

    # ===== OPENAI CALLS =====
    def _call_openai(self, messages, config, *, force_json=False, max_tokens=None, temperature=None):
        """
        Wrapper call OpenAI.
        - force_json=True: yêu cầu model trả JSON object.
        - Trả về string (nếu force_json=False) hoặc string JSON (nếu force_json=True).
        """
        try:
            import openai
            client = openai.OpenAI(api_key=config["api_key"])
            kwargs = {
                "model": config["model"],
                "messages": messages,
                "max_tokens": max_tokens if max_tokens is not None else int(config.get("max_tokens", 600)),
                "temperature": temperature if temperature is not None else float(config.get("temperature", 0.2)),
            }
            if force_json:
                # Buộc trả JSON object (các model 4o/4.1/mini đều hỗ trợ)
                kwargs["response_format"] = {"type": "json_object"}

            resp = client.chat.completions.create(**kwargs)
            if resp.choices:
                return resp.choices[0].message.content or ""
            return ""
        except ImportError:
            return "ERROR_OPENAI_NOT_INSTALLED"
        except Exception as e:
            _logger.error("OpenAI error: %s", e)
            return ""
        
        
    
    def _safe_json_from_text(self, text: str):
        """
        Cố gắng parse JSON từ text lẫn lộn:
        - Thử loads trực tiếp
        - Thử cắt khỏi ```json ... ``` hoặc ``` ... ```
        - Thử regex non-greedy { ... } (đa đối tượng) và parse lần lượt
        - Thử cân ngoặc {} để lấy object lớn nhất hợp lệ
        Trả về dict hoặc {}.
        """
        import json as _json
        s = (text or "").strip()
        if not s:
            return {}

        # 1) trực tiếp
        try:
            obj = _json.loads(s)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

        # 2) khối fenced code
        m = re.search(r"```json\s*(\{.*?\})\s*```", s, re.S | re.I)
        if m:
            try:
                obj = _json.loads(m.group(1))
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass
        m = re.search(r"```\s*(\{.*?\})\s*```", s, re.S | re.I)
        if m:
            try:
                obj = _json.loads(m.group(1))
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

        # 3) non-greedy nhiều object: lấy cái parse được đầu tiên
        candidates = re.findall(r"\{.*?\}", s, re.S)
        for cand in candidates:
            try:
                obj = _json.loads(cand)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue

        # 4) cân ngoặc: lấy vùng từ { đầu tiên tới } khớp
        start = s.find("{")
        if start != -1:
            level = 0
            for i in range(start, len(s)):
                ch = s[i]
                if ch == "{":
                    level += 1
                elif ch == "}":
                    level -= 1
                    if level == 0:
                        seg = s[start:i+1]
                        try:
                            obj = _json.loads(seg)
                            if isinstance(obj, dict):
                                return obj
                        except Exception:
                            break

        return {}



    def _ai_generate_search_plan(self, user_text: str, config: dict, tried_candidates=None, broaden=False):
        tried_candidates = tried_candidates or []
        sys_prompt = (
            "Bạn là công cụ phân tích truy vấn sản phẩm cho kho Odoo.\n"
            "Xuất JSON đúng schema, KHÔNG kèm lời giải thích.\n"
            "- Nhận diện 'is_combo' nếu có 'combo'/'cb'/dấu '+'.\n"
            "- Sinh 'candidates' đa dạng: giữ nguyên, bỏ/đổi separators (space/hyphen/underscore/slash/dot), viết liền, "
            "chuẩn 'chữ-số' ('FID 3'->'FID3'), có thể thêm biến thể phổ biến (-0, -0X, -X0, -ASIA) khi hợp lý.\n"
            "- Nếu broaden=true, mở rộng thêm 5–10 candidates thực tế.\n"
            "- Nếu là combo, giữ chuỗi có '+' và cả các thành phần riêng lẻ.\n"
            "Chỉ trả JSON object theo schema."
        )
        user_payload = {
            "query": user_text,
            "broaden": bool(broaden),
            "tried_candidates": tried_candidates[:50],
            "schema": {
                "intent": {"is_combo": True, "quantity": None, "warehouses": ["TSN"]},
                "products": [
                    {"raw": "M18 FHIW2F12+M18B5+M12-18C", "is_combo": True,
                    "candidates": ["M18 FHIW2F12+M18B5+M12-18C","FHIW2F12","M18B5","M12-18C","M1218C"]}
                ],
            },
        }

        # 1) ưu tiên JSON mode
        raw = self._call_openai(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            config={**config, "max_tokens": min(1200, int(config.get("max_tokens", 600)))},
            force_json=True,
        )

        plan = self._safe_json_from_text(raw)
        if not plan:
            # 2) fallback: gọi text-mode rồi parse an toàn
            raw2 = self._call_openai(
                messages=[
                    {"role": "system", "content": sys_prompt + "\nCHỈ TRẢ JSON."},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                config={**config, "max_tokens": min(1200, int(config.get("max_tokens", 600)))},
                force_json=False,
            )
            plan = self._safe_json_from_text(raw2) or {}

        if not isinstance(plan, dict):
            plan = {}
        plan.setdefault("intent", {})
        plan.setdefault("products", [])
        return plan


    # ===== LOCAL ENTITY EXTRACTION (fallback/assist) =====
    def _extract_entities_local(self, text: str):
        """
        Nhanh-gọn: tách fragment mã, kho & số lượng cơ bản (không AI).
        """
        t = _norm(text or "")
        # sku fragments: tách theo dấu +, dấu phẩy, khoảng trắng lớn
        frags = []
        # Ưu tiên dấu '+'
        if "+" in t:
            frags = [s.strip() for s in t.split("+") if s.strip()]
        # Tách thêm các cụm mã kiểu A1-23-456 hoặc chữ-số
        tokens = re.findall(r"[A-Za-z0-9\-_/\.]+", t)
        for tok in tokens:
            if len(tok) >= 2 and tok not in frags:
                frags.append(tok)

        # warehouse hint
        # mapping ví dụ người dùng đã nêu
        wh_hint = None
        lower = t.lower()
        if "tân sơn nhì" in lower or "tsn" in lower:
            wh_hint = "TSN"
        if "showroom" in lower or "tsnsr" in lower or "tân sơn nhì showroom" in lower:
            wh_hint = "TSNSR"
        if "bến cam" in lower or "kbc" in lower:
            wh_hint = "KBC"
        if "hiền đức" in lower or "khd" in lower:
            wh_hint = "KHD"

        # quantity
        qty = None
        m = re.search(r"\b(\d+)\s*(cai|cái|pcs|piece|chiếc)?\b", lower)
        if m:
            try:
                qty = int(m.group(1))
            except Exception:
                qty = None

        return {"sku_fragments": frags, "warehouse_hint": wh_hint, "quantity": qty}

    # ===== AI-ASSISTED SEARCH =====
    def _ai_smart_product_search(self, user_text: str, limit=20):
        """
        AI-assisted search → list of product dicts.
        """
        env = request.env
        Product = env["product.product"].sudo()
        Bom = env["mrp.bom"].sudo() if "mrp.bom" in env else None

        def _is_combo_product(prod):
            if getattr(prod.product_tmpl_id, "is_combo", False):
                return True
            if Bom:
                bom = Bom.search([("product_tmpl_id", "=", prod.product_tmpl_id.id),
                                  ("type", "in", ["phantom", "normal"])], limit=1)
                if bom:
                    return True
            if hasattr(prod.product_tmpl_id, "combo_line_ids") and prod.product_tmpl_id.combo_line_ids:
                return True
            return False

        def _get_combo_components(prod):
            comps = []
            if hasattr(prod.product_tmpl_id, "combo_line_ids") and prod.product_tmpl_id.combo_line_ids:
                for line in prod.product_tmpl_id.combo_line_ids:
                    p = line.product_id.product_variant_id or line.product_id
                    comps.append({
                        "product_id": p.id,
                        "name": p.name,
                        "default_code": p.default_code or "",
                        "uom": p.uom_id.name or "",
                        "qty": float(getattr(line, "product_qty", 1.0) or 1.0),
                    })
                return comps
            if Bom:
                bom = Bom.search([("product_tmpl_id", "=", prod.product_tmpl_id.id),
                                  ("type", "in", ["phantom", "normal"])], limit=1)
                if bom:
                    for bl in bom.bom_line_ids:
                        p = bl.product_id.product_variant_id or bl.product_id
                        comps.append({
                            "product_id": p.id,
                            "name": p.name,
                            "default_code": p.default_code or "",
                            "uom": p.uom_id.name or "",
                            "qty": float(bl.product_qty or 1.0),
                        })
            return comps

        def _score_match(prod, candidate: str):
            c = (candidate or "").strip()
            if not c:
                return 0
            c_n = _strip_seps(c).lower()
            dc = (prod.default_code or "")
            bc = (prod.barcode or "")
            nm = (prod.name or "")

            dc_n = _strip_seps(dc).lower()
            bc_n = _strip_seps(bc).lower()
            nm_n = nm.lower()

            best = 0
            if dc_n == c_n:
                best = max(best, 100)
            elif c_n and c_n in dc_n:
                best = max(best, 85)
            if bc_n == c_n:
                best = max(best, 80)
            elif c_n and c_n in bc_n:
                best = max(best, 70)
            c_l = c.lower()
            if nm_n == c_l:
                best = max(best, 65)
            elif c_l and c_l in nm_n:
                best = max(best, 55)
            return best

        def _query_products_for_candidates(cands, allow_combo=True, limit_each=60):
            results = {}
            if not cands:
                return results
            dom = []
            for cand in cands:
                if not cand:
                    continue
                # ilike cho default_code/barcode/name
                for field in ("default_code", "barcode", "name"):
                    new = [(field, "ilike", cand)]
                    dom = expression.OR([dom, new]) if dom else new
                # strip seps variant
                ss = _strip_seps(cand)
                if ss and ss != cand:
                    for field in ("default_code", "barcode", "name"):
                        new = [(field, "ilike", ss)]
                        dom = expression.OR([dom, new])
            prods = Product.search(dom or [], limit=limit_each)
            for p in prods:
                if (not allow_combo) and _is_combo_product(p):
                    continue
                sc = 0
                for cand in cands:
                    sc = max(sc, _score_match(p, cand))
                cur = results.get(p.id)
                if (cur is None) or (sc > cur[1]):
                    results[p.id] = (p, sc)
            return results

        # 1) AI tạo plan
        config = self._get_chatbot_config()
        plan = self._ai_generate_search_plan(user_text, config)
        is_combo_intent = bool(plan.get("intent", {}).get("is_combo"))

        # gom candidates, unique
        all_candidates = []
        for pr in plan.get("products", []):
            for c in (pr.get("candidates") or []):
                if c and c not in all_candidates:
                    all_candidates.append(c)

        # bổ sung từ local nếu trống
        if not all_candidates:
            local = self._extract_entities_local(user_text)
            frs = local.get("sku_fragments") or []
            for f in frs:
                if f and f not in all_candidates:
                    all_candidates.append(f)
            t = _norm(user_text)
            if t and t not in all_candidates:
                all_candidates.append(t)
                ss = _strip_seps(t)
                if ss and ss != t and ss not in all_candidates:
                    all_candidates.append(ss)
                if "+" in t:
                    parts = [x.strip() for x in t.split("+") if x.strip()]
                    for p in parts:
                        if p not in all_candidates:
                            all_candidates.append(p)

        # 2) query lần 1
        results = _query_products_for_candidates(
            all_candidates,
            allow_combo=is_combo_intent,
            limit_each=max(80, 4 * limit),
        )

        # 3) broaden nếu trắng
        if not results:
            more = self._ai_generate_search_plan(
                user_text,
                config,
                tried_candidates=all_candidates,
                broaden=True,
            )
            more_candidates = []
            for pr in more.get("products", []):
                for c in (pr.get("candidates") or []):
                    if c and c not in all_candidates and c not in more_candidates:
                        more_candidates.append(c)
            if more_candidates:
                extra = _query_products_for_candidates(
                    more_candidates,
                    allow_combo=is_combo_intent,
                    limit_each=max(80, 4 * limit),
                )
                results.update(extra)

        # 4) pack
        ranked = sorted(
            results.values(),
            key=lambda it: (-it[1], (it[0].default_code or ""), (it[0].name or "")),
        )[:limit]

        out = []
        for prod, score in ranked:
            is_combo = _is_combo_product(prod)
            comps = self._get_combo_components_cached(prod) if (is_combo and is_combo_intent) else []
            out.append({
                "id": prod.id,
                "name": prod.name,
                "default_code": prod.default_code or "",
                "barcode": prod.barcode or "",
                "uom": prod.uom_id.name or "",
                "list_price": getattr(prod, "lst_price", None) if hasattr(prod, "lst_price") else prod.list_price,
                "commercial_price": getattr(prod.product_tmpl_id, "x_studio_gi_bn_thng_mi", 0.0) or 0.0,
                "is_combo": bool(is_combo and is_combo_intent),
                "components": comps,
            })
        return out

    # small cache for combo components
    def _get_combo_components_cached(self, prod):
        cache = getattr(self, "_combo_comp_cache", None)
        if cache is None:
            cache = {}
            setattr(self, "_combo_comp_cache", cache)
        if prod.id in cache:
            return cache[prod.id]
        # compute
        comps = []
        # custom lines
        if hasattr(prod.product_tmpl_id, "combo_line_ids") and prod.product_tmpl_id.combo_line_ids:
            for line in prod.product_tmpl_id.combo_line_ids:
                p = line.product_id.product_variant_id or line.product_id
                comps.append({
                    "product_id": p.id,
                    "name": p.name,
                    "default_code": p.default_code or "",
                    "uom": p.uom_id.name or "",
                    "qty": float(getattr(line, "product_qty", 1.0) or 1.0),
                })
            cache[prod.id] = comps
            return comps
        # BOM
        Bom = request.env["mrp.bom"].sudo() if "mrp.bom" in request.env else None
        if Bom:
            bom = Bom.search([("product_tmpl_id", "=", prod.product_tmpl_id.id),
                              ("type", "in", ["phantom", "normal"])], limit=1)
            if bom:
                for bl in bom.bom_line_ids:
                    p = bl.product_id.product_variant_id or bl.product_id
                    comps.append({
                        "product_id": p.id,
                        "name": p.name,
                        "default_code": p.default_code or "",
                        "uom": p.uom_id.name or "",
                        "qty": float(bl.product_qty or 1.0),
                    })
        cache[prod.id] = comps
        return comps

    # ===== STOCK HELPERS =====
    def _allowed_warehouses(self):
        env = request.env
        Wh = env["stock.warehouse"].sudo()
        param = self._get_chatbot_config().get("allowed_warehouse_ids") or ""
        ids = [int(x) for x in param.split(",") if x.strip().isdigit()]
        if ids:
            whs = Wh.browse(ids).exists()
            if whs:
                return whs
        return Wh.search([])

    def _find_warehouse(self, hint):
        """Map text hint → stock.warehouse record (code)."""
        if not hint:
            return None
        code = str(hint).strip().upper()
        # quick aliases
        aliases = {
            "HCM": "TSN",
            "TSN": "TSN",
            "TSNSR": "TSNSR",
            "HCM_SHOWROOM": "TSNSR",
            "BENCAM": "KBC",
            "KBC": "KBC",
            "HIENDUC": "KHD",
            "KHD": "KHD",
        }
        code = aliases.get(code, code)
        Wh = request.env["stock.warehouse"].sudo()
        wh = Wh.search([("code", "=", code)], limit=1)
        return wh or None

    def _get_stock_by_warehouse(self, product_ids, warehouse=None):
        """
        Return:
        {
            product_id: {
            WH_CODE: {"onhand": x, "reserved": y, "available": x - y},
            ...
            },
            ...
        }
        """
        env = request.env
        Quant = env["stock.quant"].sudo()
        Loc = env["stock.location"].sudo()

        whs = self._allowed_warehouses()
        if warehouse:
            whs = whs.filtered(lambda w: w.id == warehouse.id) or whs
        if not whs:
            return {}

        root_id_to_wh = {w.view_location_id.id: w.code for w in whs}
        root_ids_set = set(root_id_to_wh.keys())

        domain = [
            ("product_id", "in", product_ids),
            ("location_id", "child_of", list(root_ids_set)),
        ]
        groups = Quant.read_group(
            domain,
            ["product_id", "quantity:sum", "reserved_quantity:sum", "location_id"],
            ["product_id", "location_id"],
            lazy=False,
        )

        loc_ids = {g["location_id"][0] for g in groups if g.get("location_id")}
        locs = Loc.browse(list(loc_ids)).sudo()
        id_to_parent = {l.id: (l.location_id.id or False) for l in locs}

        def find_root(loc_id: int):
            seen = set()
            cur = loc_id
            while cur and cur not in seen:
                if cur in root_ids_set:
                    return cur
                seen.add(cur)
                # nếu parent chưa cache, đọc nhanh từ DB (an toàn)
                cur = id_to_parent.get(cur) or Loc.browse(cur).location_id.id or False
            return None

        out = {}
        for g in groups:
            pid = g.get("product_id") and g["product_id"][0]
            loc_id = g.get("location_id") and g["location_id"][0]
            if not pid or not loc_id:
                continue

            root = find_root(loc_id)
            if not root:
                continue
            wh_code = root_id_to_wh.get(root)
            if not wh_code:
                continue

            onhand = float(g.get("quantity_sum") or g.get("quantity") or 0.0)
            reserved = float(g.get("reserved_quantity_sum") or g.get("reserved_quantity") or 0.0)
            available = onhand - reserved

            out.setdefault(pid, {})
            wh_bucket = out[pid].setdefault(wh_code, {"onhand": 0.0, "reserved": 0.0, "available": 0.0})
            wh_bucket["onhand"] += onhand
            wh_bucket["reserved"] += reserved
            wh_bucket["available"] += available

        return out



    # ===== AI RESPONSE (friendly) =====
    def _generate_ai_response(self, user_message, inventory_results, web_results, config, parsed_entities=None, warehouse_code=None):
        context = (
            "Bạn là trợ lý bán hàng của cửa hàng dụng cụ. "
            "Hãy trả lời ngắn gọn, thân thiện, có định dạng (in đậm tên sp), gợi ý tiếp theo. "
            "Nếu có danh sách SP, liệt kê theo mục 1., 2., 3. và bôi đậm **Tên sản phẩm**, in nghiêng mã _(Mã: ...)_.\n"
        )
        if parsed_entities:
            context += f"[THÔNG TIN TRUY VẤN] {json.dumps(parsed_entities, ensure_ascii=False)}\n"
        if warehouse_code:
            context += f"[KHO ƯU TIÊN] {warehouse_code}\n"

        if inventory_results:
            context += "DỮ LIỆU TỒN KHO (hiển thị *Tồn thực tế*):\n"
            for item in inventory_results:
                line = f"- **{item['name']}**"
                if item.get("default_code"):
                    line += f" _(Mã: {item['default_code']})_"
                # dùng tồn thực tế
                onhand_total = int(item.get("qty_onhand", 0))
                line += f" — **{onhand_total} {item.get('uom','')}** (tồn thực tế)"
                by_wh = item.get("by_warehouse") or {}
                if by_wh:
                    parts = [f"`{k}: {int(v)}`" for k, v in by_wh.items() if v]
                    if parts:
                        line += f" — theo kho: {', '.join(parts)}"
                # (tuỳ chọn) thêm chú thích khả dụng
                # avail_total = int(item.get("qty_available", 0))
                # line += f" — khả dụng: {avail_total}"
                context += line + "\n"
        else:
            context += "Không tìm thấy sản phẩm phù hợp trong kho.\n"

        if web_results and config.get("web_search_enabled"):
            context += "Tham khảo trên web:\n"
            for w in web_results[:3]:
                context += f"- {w.get('title','')} — {w.get('price','')} ({w.get('link','')})\n"

        context += "\nHãy kết thúc bằng 1 câu hỏi ngắn để tiếp tục hỗ trợ."

        messages = [
            {"role": "system", "content": context},
            {"role": "user", "content": user_message},
        ]
        text = self._call_openai(messages, config)
        if not text:
            text = "Mình đã tìm và gợi ý theo hiểu biết tốt nhất. Bạn cần mình kiểm tra lại theo mã khác không ạ?"
        return text

    # ===== SIMPLE WEB SEARCH PLACEHOLDER =====
    def _search_web(self, query):
        # Có thể tích hợp Google CSE/Bing sau này. Hiện trả kết quả mẫu.
        q = (query or "").lower()
        return [{
            "title": f"Tìm {query} trên Shopee",
            "link": f"https://shopee.vn/search?keyword={query.replace(' ', '%20')}",
            "price": "Đa dạng",
            "description": "Kết quả tham khảo",
        }]

    # ===== ROUTES =====
    @http.route('/chatbot/status', type='http', auth='public', methods=['GET'], csrf=False, website=True)
    def chatbot_status(self, **kw):
        cfg = self._get_chatbot_config()
        data = {
            "enabled": bool(cfg.get("enabled")),
            "configured": bool(cfg.get("api_key")),
            "web_search_enabled": bool(cfg.get("web_search_enabled")),
        }
        return request.make_response(json.dumps(data), headers=[("Content-Type", "application/json")])

    @http.route('/chatbot/message', type='http', auth='public', methods=['POST'], csrf=False, website=True)
    def chatbot_message(self, **kw):
        """
        Flexible input:
          - JSON: {"message": "..."}
          - Form data: message=...
        """
        try:
            # ---- parse message ----
            if request.httprequest.mimetype == "application/json":
                try:
                    data = request.jsonrequest or {}
                except Exception:
                    data = {}
                user_message = _norm(data.get("message") or "")
                # nối chữ-số để giảm miss
                user_message = re.sub(r"([A-Za-z])\s+(\d)", r"\1\2", user_message)
                user_message = re.sub(r"(\d)\s+([A-Za-z])", r"\1\2", user_message)
            else:
                user_message = _norm(request.params.get("message") or kw.get("message") or "")
            if not user_message:
                return request.make_response(json.dumps({"success": False, "error": "Empty message"}),
                                             headers=[("Content-Type", "application/json")])

            cfg = self._get_chatbot_config()
            if not cfg["enabled"]:
                return request.make_response(json.dumps({"success": False, "error": "Chatbot is not enabled"}),
                                             headers=[("Content-Type", "application/json")])
            if not cfg["api_key"]:
                # Cho phép chạy không AI? Ở đây yêu cầu AI cho smart-search.
                return request.make_response(json.dumps({"success": False, "error": "OpenAI API key not configured"}),
                                             headers=[("Content-Type", "application/json")])

            # ---- parse local hint ----
            ent_local = self._extract_entities_local(user_message)
            wh = self._find_warehouse(ent_local.get("warehouse_hint")) if ent_local.get("warehouse_hint") else None

            # ---- AI-assisted product search ----
            products = self._ai_smart_product_search(user_message, limit=20)

            # ---- Get stock per warehouse ----
            inv = []
            web_results = []
            if products:
                ids = [p["id"] for p in products]
                stock_map = self._get_stock_by_warehouse(ids, warehouse=wh)
            for p in products:
                per_wh_struct = stock_map.get(p["id"], {})  # {"TSN": {"onhand":..., "reserved":..., "available":...}, ...}
                # Tổng theo từng loại:
                total_onhand = sum(v.get("onhand", 0.0) for v in per_wh_struct.values()) if per_wh_struct else 0.0
                total_reserved = sum(v.get("reserved", 0.0) for v in per_wh_struct.values()) if per_wh_struct else 0.0
                total_available = sum(v.get("available", 0.0) for v in per_wh_struct.values()) if per_wh_struct else 0.0

                # Rút gọn by_warehouse chỉ còn "onhand" (nếu bạn muốn AI nói tồn thực tế),
                # hoặc giữ nguyên 3 số để FE render chi tiết:
                by_wh_onhand = {k: float(v.get("onhand", 0.0)) for k, v in per_wh_struct.items()}

                inv.append({
                    "id": p["id"],
                    "name": p["name"],
                    "default_code": p["default_code"],
                    "uom": p["uom"],
                    "list_price": p["list_price"],
                    "commercial_price": p["commercial_price"],
                    # số tổng
                    "qty_onhand": total_onhand,
                    "qty_reserved": total_reserved,
                    "qty_available": total_available,
                    # chi tiết theo kho (tồn thực tế)
                    "by_warehouse": by_wh_onhand,
                    "is_combo": p.get("is_combo", False),
                    "components": p.get("components", []),
                })
            else:
                if cfg["web_search_enabled"]:
                    web_results = self._search_web(user_message)

            # ---- AI final response text ----
            parsed = {
                "sku_fragments": ent_local.get("sku_fragments"),
                "warehouse_hint": ent_local.get("warehouse_hint"),
                "quantity": ent_local.get("quantity"),
            }
            ai_text = self._generate_ai_response(
                user_message=user_message,
                inventory_results=inv,
                web_results=web_results,
                config=cfg,
                parsed_entities=parsed,
                warehouse_code=(wh.code if wh else None),
            )

            payload = {
                "success": True,
                "response": ai_text,
                "inventory_results": inv,
                "web_results": web_results if cfg["web_search_enabled"] else [],
                "parsed": parsed,
                "warehouse": (wh.code if wh else None),
            }
            return request.make_response(json.dumps(payload), headers=[("Content-Type", "application/json")])

        except Exception as e:
            _logger.exception("Chatbot error")
            return request.make_response(json.dumps({"success": False, "error": str(e)}),
                                         headers=[("Content-Type", "application/json")])
