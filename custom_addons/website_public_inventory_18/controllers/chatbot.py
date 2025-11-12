# controllers/chatbot.py
# -*- coding: utf-8 -*-
import json
import logging
import re
import unicodedata

from odoo import http
from odoo.http import request
from odoo.osv import expression

_logger = logging.getLogger(__name__)


# ====== Helpers: chuẩn hoá chuỗi & alias kho ======
def _norm(s: str) -> str:
    s = (s or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))  # bỏ dấu
    s = re.sub(r"\s+", " ", s)
    return s.lower()


# Khai báo alias kho theo thực tế của bạn
# code chuẩn: TSN, TSNSR, KBC, KHD
WAREHOUSE_ALIAS_MAP = {
    # Tân Sơn Nhì (kho chính)
    "tsn": "TSN",
    "tan son nhi": "TSN",
    "tân sơn nhì": "TSN",
    "kho tan son nhi": "TSN",
    "kho tân sơn nhì": "TSN",

    # TSN_Showroom
    "tsn_showroom": "TSNSR",
    "tsnsr": "TSNSR",
    "tan son nhi showroom": "TSNSR",
    "tân sơn nhì showroom": "TSNSR",
    "showroom tan son nhi": "TSNSR",
    "showroom tân sơn nhì": "TSNSR",

    # Kho bến cam
    "kbc": "KBC",
    "ben cam": "KBC",
    "bến cam": "KBC",
    "kho ben cam": "KBC",
    "kho bến cam": "KBC",

    # Kho hiền đức
    "khd": "KHD",
    "hien duc": "KHD",
    "hiền đức": "KHD",
    "kho hien duc": "KHD",
    "kho hiền đức": "KHD",
}

# regex nhận diện fragment kiểu mã (có dấu gạch/._/)
SKU_FRAGMENT_RE = re.compile(r"[a-z0-9]+(?:[-_\/\.][a-z0-9]+)+")


def _extract_entities_local(text: str):
    """
    Bóc tách nhanh bằng luật:
      - sku_fragments: '39-055', '0-39-055', 'm18-b5'...
      - quantity: số gần 'cái/pcs/bộ', hoặc số độc lập
      - warehouse_hint: alias theo WAREHOUSE_ALIAS_MAP
    """
    raw = text or ""
    norm = _norm(raw)
    norm = re.sub(r"([a-zA-Z])\s+(\d)", r"\1\2", norm)

    # quantity
    qty = None
    m_qty = re.search(r"(\d+)\s*(cai|cái|pcs|pc|bo|bộ)?\b", norm)
    if m_qty:
        try:
            qty = int(m_qty.group(1))
        except Exception:
            qty = None
    if qty is None:
        # "mấy cái", "bao nhiêu"
        if re.search(r"\bm(ay|ấy)\b|\bbao nhieu\b|\bbao nhiêu\b", norm):
            qty = None  # có hỏi số lượng nhưng không nêu con số

    # warehouse
    warehouse_hint = None
    for alias in WAREHOUSE_ALIAS_MAP.keys():
        if alias in norm:
            warehouse_hint = alias
            break

    # sku fragments
    frags = set()
    for token in re.findall(SKU_FRAGMENT_RE, norm):
        token = token.strip("._/\\- ")
        if token:
            frags.add(token)
    if not frags:
        # dạng thuần như 39-055
        for t in re.findall(r"\b[0-9]{1,3}-[0-9]{2,3}\b", norm):
            frags.add(t)

    return {
        "sku_fragments": list(frags),
        "quantity": qty,
        "warehouse_hint": warehouse_hint,
        "raw": raw,
        "norm": norm,
    }


class ChatbotController(http.Controller):

    # ========= Cấu hình =========
    def _get_chatbot_config(self):
        """Get chatbot configuration from system parameters"""
        param = request.env["ir.config_parameter"].sudo()

        def to_bool(v, default=False):
            if v is None:
                return default
            if isinstance(v, bool):
                return v
            s = str(v).strip().lower()
            return s in ("1", "true", "yes", "y", "on")

        return {
            "enabled": to_bool(param.get_param("website_public_inventory_18.chatbot_enabled", "1"), True),
            "api_key": param.get_param("website_public_inventory_18.openai_api_key", "") or "",
            "model": param.get_param("website_public_inventory_18.openai_model", "gpt-4o-mini"),
            "max_tokens": int(param.get_param("website_public_inventory_18.chatbot_max_tokens", 600)),
            "temperature": float(param.get_param("website_public_inventory_18.chatbot_temperature", 0.2)),
            "web_search_enabled": to_bool(param.get_param("website_public_inventory_18.web_search_enabled", "0")),
        }

    # ========= Kho & Tồn =========
    def _find_warehouse(self, hint: str):
        """
        Tìm kho theo alias hoặc theo name/code gần đúng.
        """
        if not hint:
            return None
        env = request.env
        code = WAREHOUSE_ALIAS_MAP.get(hint, hint)
        Wh = env["stock.warehouse"].sudo()

        # ưu tiên code
        wh = Wh.search([("code", "ilike", code)], limit=1)
        if wh:
            return wh

        # fallback name
        wh = Wh.search([("name", "ilike", code)], limit=1)
        return wh or None

    def _mk_patterns_from_fragments(self, frags):
        """
        Từ fragment tạo ra các pattern để tìm:
          '39-055' -> '39-055', '39055', '0-39-055'
        """
        pats = set()
        for f in frags or []:
            f = f.strip()
            if not f:
                continue
            pats.add(f)
            pats.add(f.replace("-", "").replace("_", "").replace("/", "").replace(".", ""))
            if not f.startswith("0-"):
                pats.add("0-" + f)
        return list(pats)

    def _flexible_product_search(self, query_text: str, sku_fragments=None, limit=20):
        """
        Tìm sản phẩm linh hoạt theo default_code / barcode / name với nhiều pattern & thứ tự ưu tiên.
        Trả về: [{id, name, default_code, barcode, uom, list_price, commercial_price}, ...]
        """
        import re
        from odoo.osv import expression

        # ---------- Chuẩn hoá input ----------
        query_text = re.sub(r"\s+", " ", query_text or "").strip()
        # Nối chữ–số và số–chữ (FID 3 -> FID3; 3 AH -> 3AH)
        query_text = re.sub(r"([A-Za-z])\s+(\d)", r"\1\2", query_text)
        query_text = re.sub(r"(\d)\s+([A-Za-z])", r"\1\2", query_text)

        env = request.env
        Product = env["product.product"].sudo()

        # ---------- Lấy fragments ----------
        frags = sku_fragments or []
        if not frags and query_text:
            frags = _extract_entities_local(query_text).get("sku_fragments", []) or []

        # Nếu không có fragment nào, thử coi cả câu hỏi là 1 fragment "mềm"
        if not frags and query_text:
            frags = [query_text]

        # ---------- Tạo patterns ----------
        def _strip_seps(s):
            return re.sub(r"[\s\-\_\/\.]+", "", s or "")

        base_patterns = self._mk_patterns_from_fragments(frags)  # đã gồm: nguyên bản, loại sep, thêm "0-"
        more = []
        for p in list(base_patterns):
            sp = _strip_seps(p)
            if sp and sp != p:
                more.append(sp)
        patterns = list(dict.fromkeys(base_patterns + more))  # unique & giữ thứ tự

        # ---------- Tìm kiếm & chấm điểm ----------
        results = {}  # pid -> (product, score)

        def _add_products(prods, score_fn):
            for p in prods:
                cur = results.get(p.id)
                sc = score_fn(p)
                if (cur is None) or (sc > cur[1]):
                    results[p.id] = (p, sc)

        # 1) default_code ưu tiên cao nhất
        if patterns:
            # exact-like (so sánh dạng strip-seps) -> điểm rất cao
            dom_dc = ["|"] * (len(patterns) - 1)
            for pat in patterns:
                dom_dc += [("default_code", "ilike", pat)]
            prods_dc = Product.search(dom_dc, limit=limit * 3)  # kéo rộng, sẽ sàng điểm & cắt sau

            def score_default_code(prod):
                dc = (prod.default_code or "")
                dc_norm = _strip_seps(dc).lower()
                best = 0
                for pat in patterns:
                    p_norm = _strip_seps(pat).lower()
                    if not p_norm:
                        continue
                    if dc_norm == p_norm:
                        best = max(best, 100)    # trùng tuyệt đối (bỏ sep)
                    elif p_norm in dc_norm:
                        best = max(best, 80)     # chứa
                return best if best else 0

            _add_products(prods_dc, score_default_code)

        # 2) barcode (nếu có)
        if patterns:
            dom_bc = ["|"] * (len(patterns) - 1)
            for pat in patterns:
                dom_bc += [("barcode", "ilike", pat)]
            prods_bc = Product.search(dom_bc, limit=limit * 2)

            def score_barcode(prod):
                bc = (prod.barcode or "").lower()
                best = 0
                for pat in patterns:
                    p = pat.lower()
                    if not p:
                        continue
                    if bc == p:
                        best = max(best, 75)
                    elif p in bc:
                        best = max(best, 65)
                return best

            _add_products(prods_bc, score_barcode)

        # 3) name (ưu tiên thấp hơn default_code)
        if patterns:
            dom_nm = ["|"] * (len(patterns) - 1)
            for pat in patterns:
                dom_nm += [("name", "ilike", pat)]
            prods_nm = Product.search(dom_nm, limit=limit * 2)

            def score_name(prod):
                name = (prod.name or "").lower()
                best = 0
                for pat in patterns:
                    p = pat.lower()
                    if not p:
                        continue
                    if name == p:
                        best = max(best, 60)
                    elif p in name:
                        best = max(best, 50)
                return best

            _add_products(prods_nm, score_name)

        # 4) fallback theo token từ câu hỏi (OR) nếu vẫn ít
        # cuối hàm, trước khi hợp kết quả, nếu kết quả còn ít thì dùng AND thay vì OR
        if len(results) < 2 and query_text:
            # bỏ ngoặc/ dấu phẩy, gộp lại
            q_clean = re.sub(r"[()]+", " ", query_text)
            tokens_and = [t for t in re.split(r"[\s,;/]+", _norm(q_clean)) if len(t) >= 2 and not t.isdigit()]
            if tokens_and:
                # name chứa tất cả token
                dom = []
                for t in tokens_and:
                    dom = expression.AND([dom, [("name", "ilike", t)]]) if dom else [("name", "ilike", t)]
                prods_and = Product.search(dom, limit=limit)
                for p in prods_and:
                    if p.id not in seen:
                        seen.add(p.id)
                        results.append(p)


        # ---------- Sắp xếp theo điểm & cắt limit ----------
        ranked = sorted(results.values(), key=lambda it: (-it[1], (it[0].default_code or ""), it[0].name or ""))
        ranked = ranked[:limit]

        # ---------- Chuẩn hoá output ----------
        out = []
        for prod, _score in ranked:
            out.append({
                "id": prod.id,
                "name": prod.name,
                "default_code": prod.default_code or "",
                "barcode": prod.barcode or "",
                "uom": prod.uom_id.name or "",
                "list_price": getattr(prod, "lst_price", None) if hasattr(prod, "lst_price") else prod.list_price,
                "commercial_price": getattr(prod.product_tmpl_id, "x_studio_gi_bn_thng_mi", 0.0) or 0.0,
            })
        return out


    def _get_stock_by_warehouse(self, product_ids, warehouse=None):
        """
        Gom tồn theo kho cho các product_ids.
        Nếu warehouse được chỉ định: chỉ tính tồn trong cây location của kho đó.
        """
        env = request.env
        Quant = env["stock.quant"].sudo()
        Location = env["stock.location"].sudo()

        if warehouse:
            locs = Location.search([
                ("id", "child_of", warehouse.view_location_id.id),
                ("usage", "=", "internal"),
            ])
            wh_label_by_loc = {loc.id: (warehouse.code or warehouse.name) for loc in locs}
        else:
            locs = Location.search([("usage", "=", "internal")])
            # map location -> warehouse first match
            wh_label_by_loc = {}
            warehouses = env["stock.warehouse"].sudo().search([])
            for loc in locs:
                matched = None
                for w in warehouses:
                    # location thuộc cây của w?
                    if loc.id in Location.search([("id", "child_of", w.view_location_id.id)]).ids:
                        matched = w
                        break
                wh_label_by_loc[loc.id] = (matched.code or matched.name) if matched else loc.display_name

        quants = Quant.read_group(
            domain=[("product_id", "in", product_ids), ("location_id", "in", locs.ids)],
            fields=["product_id", "location_id", "quantity:sum", "reserved_quantity:sum"],
            groupby=["product_id", "location_id"],
            lazy=False,
        )

        out = {}
        for row in quants:
            pid = row["product_id"][0]
            loc_id = row["location_id"][0]
            qty = float(row.get("quantity_sum") or row.get("quantity") or 0.0)
            res = float(row.get("reserved_quantity_sum") or row.get("reserved_quantity") or 0.0)
            avail = qty - res
            wh_label = wh_label_by_loc.get(loc_id) or "UNKNOWN"

            out.setdefault(pid, {})
            out[pid][wh_label] = out[pid].get(wh_label, 0.0) + max(avail, 0.0)
        return out

    # ========= Web search (stub) =========
    def _search_web(self, query):
        try:
            # placeholder: trả vài gợi ý tham khảo
            return [{
                "title": f"Tìm {query} trên Shopee",
                "link": f"https://shopee.vn/search?keyword={query.replace(' ', '%20')}",
                "price": "Giá đa dạng",
                "description": "Kết quả tham khảo, không đảm bảo chính xác."
            }]
        except Exception as e:
            _logger.error("Web search error: %s", e)
            return []

    # ========= OpenAI: gọi & (tuỳ chọn) bóc tách thực thể bằng AI =========
    def _call_openai(self, messages, config):
        try:
            import openai
            client = openai.OpenAI(api_key=config["api_key"])
            resp = client.chat.completions.create(
                model=config.get("model") or "gpt-4o-mini",
                messages=messages,
                temperature=float(config.get("temperature", 0.2)),
                max_tokens=int(config.get("max_tokens", 600)),
            )
            if resp and resp.choices:
                return resp.choices[0].message.content
            return "Xin lỗi, tôi không thể xử lý yêu cầu này."
        except ImportError:
            return "Lỗi: OpenAI library chưa được cài đặt."
        except Exception as e:
            _logger.exception("OpenAI API error")
            return f"Lỗi khi gọi AI: {str(e)}"

    def _ai_extract_entities(self, user_message, config):
        """
        Nhờ AI trích xuất JSON {sku_fragments:[], warehouse_name:'', quantity:int|null}
        Dùng khi luật local không rõ ràng.
        """
        try:
            system = (
                "Bạn là trình bóc tách thực thể cho câu hỏi kho hàng. "
                "Hãy trả về JSON với các khóa: sku_fragments (list string), "
                "warehouse_name (string hoặc rỗng), quantity (số hoặc null). "
                "Không giải thích, chỉ in JSON hợp lệ."
            )
            user = f"Câu người dùng: {user_message}\nLưu ý: SKU có thể là fragment như '39-055' tương ứng '0-39-055'. Kho có thể: Tân Sơn Nhì (TSN), TSN_Showroom, Kho bến cam (KBC), Kho hiền đức (KHD)."
            txt = self._call_openai(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                config=config,
            )
            # cố parse JSON
            m = re.search(r"\{.*\}", txt, re.S)
            if not m:
                return {}
            data = json.loads(m.group(0))
            out = {}
            if isinstance(data.get("sku_fragments"), list):
                out["sku_fragments"] = [str(x) for x in data["sku_fragments"] if str(x).strip()]
            wh = str(data.get("warehouse_name") or "").strip()
            out["warehouse_hint"] = _norm(wh) if wh else None
            q = data.get("quantity")
            out["quantity"] = int(q) if isinstance(q, (int, float)) else None
            return out
        except Exception:
            return {}

    # ========= Tạo câu trả lời =========
    def _generate_ai_response(self, user_message, inventory_results, web_results, config,
                              parsed_entities=None, warehouse_code=None):
        ent = parsed_entities or {}
        sku_fragments = ent.get("sku_fragments") or []
        qty = ent.get("quantity")
        wh = warehouse_code

        context = f"""Bạn là trợ lý AI cho hệ thống kho.

Mục tiêu:
- Hiểu SKU có thể là fragment (ví dụ '39-055' tương ứng '0-39-055').
- Nhận diện kho nếu người dùng nêu ('Tân Sơn Nhì' ~ 'TSN', 'TSN_Showroom', 'Kho bến cam' ~ 'KBC', 'Kho hiền đức' ~ 'KHD').
- Nếu người dùng hỏi số lượng, so sánh với tồn (ưu tiên theo kho đã chỉ định).
- Trả lời ngắn gọn, rõ ràng, lịch sự, dùng tiếng Việt tự nhiên.

THÔNG TIN BÓC TÁCH:
- SKU fragments: {", ".join(sku_fragments) if sku_fragments else "Không phát hiện"}
- Kho yêu cầu: {wh or "Không xác định"}
- Số lượng hỏi: {qty if qty is not None else "Không nêu"}
"""
        if inventory_results:
            context += "📦 TỒN KHO HIỆN TẠI:\n"
            for i, item in enumerate(inventory_results, start=1):
                name = (item.get("name") or "").replace("*", "")
                code = item.get("default_code") or ""
                uom  = item.get("uom") or ""
                total = int(item.get("qty_available", 0))
                by_wh = item.get("by_warehouse") or {}
                price = int(item.get("list_price", 0))
                cp = int(item.get("commercial_price", 0))

                line = f"{i}. **{name}** _(Mã: {code})_ có **{total} {uom}**"
                if by_wh:
                    parts = [f"`{k}: {int(v)}`" for k, v in by_wh.items()]
                    line += " với chi tiết: " + ", ".join(parts)
                line += f". 💰 Giá lẻ: **{price:,} VND**"
                if cp and cp != price:
                    line += f", TM: **{cp:,} VND**"
                context += line + "\n"
        else:
            context += "❌ Không tìm thấy sản phẩm phù hợp trong kho.\n"

            if web_results and config.get("web_search_enabled"):
                context += "🌐 Kết quả web (tham khảo):\n"
                for w in web_results[:5]:
                    title = w.get("title","")
                    price = w.get("price","")
                    link  = w.get("link","")
                    context += f"- **{title}**: {price} | {link}\n"


        context += """
            QUY ƯỚC TRÌNH BÀY:
            - Luôn **in đậm tên sản phẩm**; mã sản phẩm dùng _nghiêng_, tồn/kho/giá dùng **đậm**.
            - Mỗi sản phẩm 1 dòng gọn, kho hiển thị dạng `KHO: số`.
            HƯỚNG DẪN TRẢ LỜI:
            - Nếu có kho yêu cầu (ví dụ TSN): nêu tồn của kho đó đầu tiên.
            - Nếu người dùng chỉ gõ fragment (ví dụ '39-055'), hãy xác nhận tương ứng với mã đầy đủ nếu nhận diện được (ví dụ '0-39-055').
            - Nếu không tìm thấy, gợi ý kiểm tra lại mã hoặc mô tả chi tiết hơn.
            - Kết thúc bằng 1 câu hỏi ngắn để tiếp tục hỗ trợ.
            - Đây là đoạn chat phục vụ người dùng nội bộ (saler, thủ kho) không phải của khách hàng
            """

        messages = [
            {"role": "system", "content": context},
            {"role": "user", "content": user_message},
        ]
        return self._call_openai(messages, config)

    # ========= Routes =========
    @http.route('/chatbot/status', type='http', auth='public', methods=['GET'], csrf=False, website=True)
    def chatbot_status(self, **kw):
        config = self._get_chatbot_config()
        data = {
            "enabled": bool(config.get("enabled")),
            "configured": bool(config.get("api_key")),
            "web_search_enabled": bool(config.get("web_search_enabled")),
        }
        return request.make_response(json.dumps(data), headers=[("Content-Type", "application/json")])
@http.route('/chatbot/message', type='http', auth='public', methods=['POST'], csrf=False, website=True)
def chatbot_message(self, **kw):
    """
    Nhận input linh hoạt:
      - Content-Type: application/json  -> request.jsonrequest
      - Form/x-www-form-urlencoded      -> request.params/kw
    Bóc tách thực thể (local + AI fallback), tìm sản phẩm theo fragment,
    quy ra tồn theo kho, rồi sinh câu trả lời. Đồng bộ số lượng item giữa
    câu trả lời AI và danh sách trả về FE bằng cách cắt TOP_K.
    """
    import json
    import re

    def _normalize_user_text(s: str) -> str:
        s = re.sub(r"\s+", " ", (s or "")).strip()
        # Nối chữ–số và số–chữ: "FID 3" -> "FID3", "3 AH" -> "3AH"
        s = re.sub(r"([A-Za-z])\s+(\d)", r"\1\2", s)
        s = re.sub(r"(\d)\s+([A-Za-z])", r"\1\2", s)
        return s

    try:
        # ---------------- Input ----------------
        content_type = (request.httprequest.content_type or "").lower()
        user_message = ""

        if "application/json" in content_type:
            try:
                data = request.jsonrequest or {}
            except Exception:
                data = {}
            user_message = _normalize_user_text(data.get("message") or "")
        else:
            user_message = _normalize_user_text(
                request.params.get("message") or kw.get("message") or ""
            )

        # ---------------- Config checks ----------------
        config = self._get_chatbot_config()
        if not config.get("enabled"):
            payload = {"success": False, "error": "Chatbot is not enabled"}
            return request.make_response(json.dumps(payload, ensure_ascii=False),
                                         headers=[("Content-Type", "application/json")])

        if not user_message:
            payload = {"success": False, "error": "Empty message"}
            return request.make_response(json.dumps(payload, ensure_ascii=False),
                                         headers=[("Content-Type", "application/json")])

        # Lưu ý: có thể cho phép chạy "không AI" nếu muốn.
        if not config.get("api_key"):
            payload = {"success": False, "error": "OpenAI API key not configured"}
            return request.make_response(json.dumps(payload, ensure_ascii=False),
                                         headers=[("Content-Type", "application/json")])

        # ---------------- Entity extraction ----------------
        ent_local = _extract_entities_local(user_message) or {}
        need_ai = (not ent_local.get("sku_fragments")) and (not ent_local.get("warehouse_hint"))
        ent_ai = self._ai_extract_entities(user_message, config) if need_ai else {}

        # Merge (AI > local nếu có giá trị)
        sku_frags = ent_ai.get("sku_fragments") or ent_local.get("sku_fragments") or []
        warehouse_hint = ent_ai.get("warehouse_hint") or ent_local.get("warehouse_hint")
        asked_qty = ent_ai.get("quantity") if ent_ai.get("quantity") is not None else ent_local.get("quantity")

        # ---------------- Warehouse resolve ----------------
        wh = self._find_warehouse(warehouse_hint) if warehouse_hint else None

        # ---------------- Product search ----------------
        # trả về đã sắp xếp theo mức độ khớp (trong _flexible_product_search)
        raw_products = self._flexible_product_search(user_message, sku_fragments=sku_frags, limit=20)

        # ---------------- Stock by warehouse ----------------
        stock_map = {}
        if raw_products:
            prod_ids = [p["id"] for p in raw_products]
            stock_map = self._get_stock_by_warehouse(prod_ids, warehouse=wh)  # {product_id: {WH: qty, ...}}

        # ---------------- Build inventory_results ----------------
        inv = []
        for p in raw_products:
            per_wh = stock_map.get(p["id"], {}) or {}
            qty_total = float(sum(per_wh.values())) if per_wh else 0.0
            inv.append({
                "id": p["id"],
                "name": p.get("name") or "",
                "default_code": p.get("default_code") or "",
                "barcode": p.get("barcode") or "",
                "uom": p.get("uom") or "",
                "list_price": p.get("list_price") or 0.0,
                "commercial_price": p.get("commercial_price") or 0.0,
                "qty_available": qty_total,
                "by_warehouse": per_wh,  # ví dụ {"TSN": 7, "TSNSR": 1}
            })

        # ---------------- Keep results small & coherent ----------------
        # CẮT TOP_K để đồng bộ: AI chỉ thấy và FE chỉ nhận ngần ấy.
        TOP_K = 3
        selected_inv = inv[:TOP_K]

        # ---------------- Web search (fallback) ----------------
        web_results = []
        if not selected_inv and config.get("web_search_enabled"):
            web_results = self._search_web(user_message)

        # ---------------- AI response ----------------
        parsed = {
            "sku_fragments": sku_frags,
            "warehouse_hint": warehouse_hint,
            "quantity": asked_qty,
        }
        ai_response = self._generate_ai_response(
            user_message=user_message,
            inventory_results=selected_inv,
            web_results=web_results,
            config=config,
            parsed_entities=parsed,
            warehouse_code=(wh.code if wh else None),
        )

        payload = {
            "success": True,
            "response": ai_response,
            "inventory_results": selected_inv,  # chỉ trả đúng những gì AI đã thấy
            "web_results": web_results if config.get("web_search_enabled") else [],
            "parsed": parsed,
            "warehouse": (wh.code if wh else None),
        }
        return request.make_response(json.dumps(payload, ensure_ascii=False),
                                     headers=[("Content-Type", "application/json")])

    except Exception as e:
        _logger.exception("Chatbot error")
        payload = {"success": False, "error": str(e)}
        return request.make_response(json.dumps(payload, ensure_ascii=False),
                                     headers=[("Content-Type", "application/json")])
