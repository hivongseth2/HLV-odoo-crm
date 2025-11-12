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
        Tìm sản phẩm linh hoạt theo default_code / name với nhiều pattern.
        """
        
        query_text = re.sub(r"\s+", " ", query_text or "").strip() 
        env = request.env
        Product = env["product.product"].sudo()

        frags = sku_fragments or []
        if not frags and query_text:
            frags = _extract_entities_local(query_text)["sku_fragments"]

        patterns = self._mk_patterns_from_fragments(frags)
        results = []
        seen = set()

        # 1) default_code
        if patterns:
            dom = ["|"] * (len(patterns) - 1)
            for p in patterns:
                dom += [("default_code", "ilike", p)]
            prods = Product.search(dom, limit=limit)
            for p in prods:
                if p.id not in seen:
                    seen.add(p.id)
                    results.append(p)

        # 2) name (nếu ít)
        if len(results) < 5 and patterns:
            dom = ["|"] * (len(patterns) - 1)
            for p in patterns:
                dom += [("name", "ilike", p)]
            prods = Product.search(dom, limit=limit)
            for p in prods:
                if p.id not in seen:
                    seen.add(p.id)
                    results.append(p)

        # 3) tokens từ câu hỏi
        if len(results) < 3 and query_text:
            tokens = [t for t in re.split(r"[\s,;/]+", _norm(query_text)) if t and not t.isdigit()]
            dom = []
            for t in tokens:
                dom += [("name", "ilike", t)]
            if dom:
                prods = Product.search(dom, limit=limit)
                for p in prods:
                    if p.id not in seen:
                        seen.add(p.id)
                        results.append(p)

        out = []
        for p in results[:limit]:
            out.append({
                "id": p.id,
                "name": p.name,
                "default_code": p.default_code or "",
                "barcode": p.barcode or "",
                "uom": p.uom_id.name or "",
                "list_price": p.lst_price or 0.0,
                "commercial_price": getattr(p.product_tmpl_id, "x_studio_gi_bn_thng_mi", 0.0) or 0.0,
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
            for item in inventory_results:
                line = f"- {item['name']}"
                if item.get("default_code"):
                    line += f" (Mã: {item['default_code']})"
                total = item.get("qty_available", 0)
                line += f" | Tổng tồn: {int(total)} {item.get('uom','')}"
                by_wh = item.get("by_warehouse") or {}
                if by_wh:
                    parts = [f"{k}: {int(v)}" for k, v in by_wh.items()]
                    line += " | Theo kho: " + ", ".join(parts)
                line += f" | Giá lẻ: {int(item.get('list_price', 0)):,} VND"
                cp = item.get("commercial_price") or 0
                if cp and cp != item.get("list_price"):
                    line += f" | Giá TM: {int(cp):,} VND"
                context += line + "\n"
        else:
            context += "❌ Không tìm thấy sản phẩm phù hợp trong kho.\n"
            if web_results and config.get("web_search_enabled"):
                context += "🌐 Kết quả web (tham khảo):\n"
                for w in web_results[:5]:
                    context += f"- {w.get('title','')}: {w.get('price','')} | {w.get('link','')}\n"

        context += """
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
        quy ra tồn theo kho, rồi sinh câu trả lời.
        """
        try:
            # ---- Lấy message ----
            if request.httprequest.mimetype == "application/json":
                data = request.jsonrequest or {}
                user_message = (data.get("message") or "").strip()
                user_message = re.sub(r"\s+", " ", user_message).strip()

            else:
                user_message = (request.params.get("message") or kw.get("message") or "").strip()

            config = self._get_chatbot_config()
            if not config["enabled"]:
                return request.make_response(json.dumps({"success": False, "error": "Chatbot is not enabled"}),
                                             headers=[("Content-Type", "application/json")])
            if not config["api_key"]:
                # Bạn có thể đổi thành cho phép chạy "không AI" nếu muốn
                return request.make_response(json.dumps({"success": False, "error": "OpenAI API key not configured"}),
                                             headers=[("Content-Type", "application/json")])
            if not user_message:
                return request.make_response(json.dumps({"success": False, "error": "Empty message"}),
                                             headers=[("Content-Type", "application/json")])

            # ---- Bóc tách local ----
            ent_local = _extract_entities_local(user_message)

            # ---- Bóc tách AI (fallback nếu local mơ hồ) ----
            ent_ai = {}
            need_ai = (not ent_local.get("sku_fragments")) and (not ent_local.get("warehouse_hint"))
            if need_ai:
                ent_ai = self._ai_extract_entities(user_message, config)

            # Merge entities (AI thắng khi có giá trị)
            sku_frags = ent_ai.get("sku_fragments") or ent_local.get("sku_fragments") or []
            warehouse_hint = ent_ai.get("warehouse_hint") or ent_local.get("warehouse_hint")
            asked_qty = ent_ai.get("quantity") if ent_ai.get("quantity") is not None else ent_local.get("quantity")

            # ---- Xác định kho ----
            wh = self._find_warehouse(warehouse_hint) if warehouse_hint else None

            # ---- Tìm sản phẩm theo fragment linh hoạt ----
            products = self._flexible_product_search(user_message, sku_fragments=sku_frags, limit=20)

            # ---- Lấy tồn theo kho ----
            stock_map = {}
            if products:
                ids = [p["id"] for p in products]
                stock_map = self._get_stock_by_warehouse(ids, warehouse=wh)

            # ---- Đóng gói inventory_results cho AI/FE ----
            inv = []
            for p in products:
                per_wh = stock_map.get(p["id"], {})
                qty_total = sum(per_wh.values()) if per_wh else 0.0
                inv.append({
                    "id": p["id"],
                    "name": p["name"],
                    "default_code": p["default_code"],
                    "uom": p["uom"],
                    "list_price": p["list_price"],
                    "commercial_price": p["commercial_price"],
                    "qty_available": qty_total,
                    "by_warehouse": per_wh,  # ví dụ {"TSN": 12, "KBC": 3}
                })

            # ---- Web search nếu không thấy trong kho ----
            web_results = []
            if not inv and config["web_search_enabled"]:
                web_results = self._search_web(user_message)

            # ---- Trả lời bằng AI (có thêm context kho + qty) ----
            parsed = {
                "sku_fragments": sku_frags,
                "warehouse_hint": warehouse_hint,
                "quantity": asked_qty,
            }
            ai_response = self._generate_ai_response(
                user_message=user_message,
                inventory_results=inv,
                web_results=web_results,
                config=config,
                parsed_entities=parsed,
                warehouse_code=(wh.code if wh else None),
            )

            payload = {
                "success": True,
                "response": ai_response,
                "inventory_results": inv,
                "web_results": web_results if config["web_search_enabled"] else [],
                "parsed": parsed,
                "warehouse": (wh.code if wh else None),
            }
            return request.make_response(json.dumps(payload), headers=[("Content-Type", "application/json")])

        except Exception as e:
            _logger.exception("Chatbot error")
            return request.make_response(json.dumps({"success": False, "error": str(e)}),
                                         headers=[("Content-Type", "application/json")])
