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


def _normalize_for_search(s: str) -> str:
    """
    Chuẩn hóa mạnh mẽ để so khớp:
    - Loại bỏ space, dash, underscore, slash, dot
    - Chuyển về uppercase
    - Giữ lại chỉ chữ và số
    """
    s = (s or "").upper()
    s = re.sub(r"[\s\-\_\/\.]+", "", s)
    return s


def _detect_combo_query(text: str) -> dict:
    """
    Phát hiện xem query có phải combo không.
    Return: {
        "is_combo": bool,
        "raw_parts": [list của các phần],
        "normalized_parts": [list đã chuẩn hóa]
    }
    """
    text = (text or "").strip()
    is_combo = False
    raw_parts = []
    
    # Dấu hiệu combo: có dấu '+'
    if "+" in text:
        is_combo = True
        raw_parts = [p.strip() for p in text.split("+") if p.strip()]
    
    # Dấu hiệu combo: có từ "combo"
    if "combo" in text.lower():
        is_combo = True
        # Cố gắng tách các mã từ text
        # Ví dụ: "Combo Máy khoan đục bê tông Milwaukee M18 FHX + 1 pin M18B5+ 1 sạc M12-18C"
        tokens = re.findall(r"[A-Za-z0-9][\w\-/\.]*", text)
        # Lọc những token có vẻ là mã sản phẩm (chứa cả chữ và số)
        for tok in tokens:
            if re.search(r"[A-Za-z]", tok) and re.search(r"\d", tok):
                if tok not in raw_parts:
                    raw_parts.append(tok)
    
    # Dấu hiệu combo: pattern "CB-..." hoặc có nhiều mã ghép bằng space
    if text.upper().startswith("CB-") or text.upper().startswith("CB "):
        is_combo = True
        # Tách theo pattern mã sản phẩm
        tokens = re.findall(r"[A-Z0-9][\w\-/\.]+", text.upper())
        for tok in tokens:
            if tok not in raw_parts:
                raw_parts.append(tok)
    
    normalized_parts = [_normalize_for_search(p) for p in raw_parts]
    
    return {
        "is_combo": is_combo,
        "raw_parts": raw_parts,
        "normalized_parts": normalized_parts
    }


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
            "allowed_warehouse_ids": param.get_param("website_public_inventory_18.allowed_warehouse_ids", default=""),
        }

    # ===== OPENAI CALLS =====
    def _call_openai(self, messages, config, *, force_json=False, max_tokens=None, temperature=None):
        """Wrapper call OpenAI."""
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
        """Parse JSON từ text có thể lẫn lộn."""
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

        # 3) non-greedy
        candidates = re.findall(r"\{.*?\}", s, re.S)
        for cand in candidates:
            try:
                obj = _json.loads(cand)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue

        # 4) cân ngoặc
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

    # ===== FLEXIBLE PRODUCT SEARCH =====
    def _flexible_product_search(self, user_text: str, limit=20):
        """
        Tìm kiếm flexible theo cách:
        1. Load tất cả sản phẩm có default_code hoặc name
        2. Chuẩn hóa query và tất cả mã/tên
        3. So khớp bằng fuzzy matching
        4. Xử lý đặc biệt cho combo
        """
        env = request.env
        Product = env["product.product"].sudo()
        Bom = env["mrp.bom"].sudo() if "mrp.bom" in env else None

        # Phát hiện combo
        combo_info = _detect_combo_query(user_text)
        is_combo_query = combo_info["is_combo"]
        
        # Chuẩn hóa query
        query_normalized = _normalize_for_search(user_text)
        
        # Load tất cả sản phẩm (có thể cache sau này)
        all_products = Product.search([
            '|', 
            ('default_code', '!=', False),
            ('name', '!=', False)
        ], limit=5000)  # Giới hạn để tránh quá tải
        
        def _is_combo_product(prod):
            """Kiểm tra xem sản phẩm có phải combo không."""
            # Kiểm tra field is_combo
            if getattr(prod.product_tmpl_id, "is_combo", False):
                return True
            # Kiểm tra BOM
            if Bom:
                bom = Bom.search([
                    ("product_tmpl_id", "=", prod.product_tmpl_id.id),
                    ("type", "in", ["phantom", "normal"])
                ], limit=1)
                if bom:
                    return True
            # Kiểm tra combo_line_ids
            if hasattr(prod.product_tmpl_id, "combo_line_ids") and prod.product_tmpl_id.combo_line_ids:
                return True
            return False
        
        def _get_combo_components(prod):
            """Lấy danh sách component của combo."""
            comps = []
            # Từ combo_line_ids
            if hasattr(prod.product_tmpl_id, "combo_line_ids") and prod.product_tmpl_id.combo_line_ids:
                for line in prod.product_tmpl_id.combo_line_ids:
                    p = line.product_id
                    comps.append({
                        "product_id": p.id,
                        "name": p.name,
                        "default_code": p.default_code or "",
                        "uom": p.uom_id.name or "",
                        "qty": float(getattr(line, "product_qty", 1.0) or 1.0),
                    })
                return comps
            # Từ BOM
            if Bom:
                bom = Bom.search([
                    ("product_tmpl_id", "=", prod.product_tmpl_id.id),
                    ("type", "in", ["phantom", "normal"])
                ], limit=1)
                if bom:
                    for bl in bom.bom_line_ids:
                        p = bl.product_id
                        comps.append({
                            "product_id": p.id,
                            "name": p.name,
                            "default_code": p.default_code or "",
                            "uom": p.uom_id.name or "",
                            "qty": float(bl.product_qty or 1.0),
                        })
            return comps
        
        def _fuzzy_score(prod, query_norm, is_combo_search=False):
            """
            Tính điểm khớp giữa product và query.
            Score càng cao = khớp càng tốt.
            """
            code = _normalize_for_search(prod.default_code or "")
            name = _normalize_for_search(prod.name or "")
            barcode = _normalize_for_search(prod.barcode or "")
            
            score = 0
            
            # Khớp hoàn toàn default_code
            if code and code == query_norm:
                score += 100
            # Khớp bộ phận default_code
            elif code and query_norm in code:
                score += 80
            elif code and code in query_norm:
                score += 70
            
            # Khớp barcode
            if barcode and barcode == query_norm:
                score += 90
            elif barcode and query_norm in barcode:
                score += 60
            
            # Khớp name
            if name and query_norm in name:
                score += 50
            elif name and name in query_norm:
                score += 40
            
            # Thưởng điểm cho combo nếu đang tìm combo
            if is_combo_search and _is_combo_product(prod):
                score += 30
            
            # Phạt điểm nếu tìm combo nhưng không phải combo
            if is_combo_search and not _is_combo_product(prod):
                score -= 20
            
            return max(0, score)
        
        # Nếu là combo query, cần match từng component
        if is_combo_query and combo_info["normalized_parts"]:
            # Tìm các sản phẩm khớp với từng phần
            component_matches = {}
            for part_norm in combo_info["normalized_parts"]:
                for prod in all_products:
                    score = _fuzzy_score(prod, part_norm, is_combo_search=False)
                    if score > 50:  # threshold
                        if prod.id not in component_matches:
                            component_matches[prod.id] = {
                                "product": prod,
                                "score": score,
                                "matched_parts": []
                            }
                        component_matches[prod.id]["matched_parts"].append(part_norm)
                        component_matches[prod.id]["score"] = max(
                            component_matches[prod.id]["score"], 
                            score
                        )
            
            # Tìm combo chứa các component này
            combo_results = {}
            for prod in all_products:
                if not _is_combo_product(prod):
                    continue
                
                comps = _get_combo_components(prod)
                comp_ids = {c["product_id"] for c in comps}
                
                # Tính điểm dựa trên số component khớp
                matched_count = sum(1 for cid in comp_ids if cid in component_matches)
                if matched_count > 0:
                    combo_score = matched_count * 50 + _fuzzy_score(prod, query_normalized, True)
                    combo_results[prod.id] = {
                        "product": prod,
                        "score": combo_score,
                        "is_combo": True,
                        "components": comps
                    }
            
            # Kết hợp kết quả: combo trước, rồi đến component
            all_results = combo_results.copy()
            for cid, cdata in component_matches.items():
                if cid not in all_results:
                    all_results[cid] = {
                        "product": cdata["product"],
                        "score": cdata["score"],
                        "is_combo": False,
                        "components": []
                    }
        else:
            # Tìm kiếm thông thường - LOẠI BỎ CÁC SẢN PHẨM COMBO
            all_results = {}
            for prod in all_products:
                # Bỏ qua sản phẩm combo nếu không phải combo query
                if _is_combo_product(prod):
                    continue
                
                score = _fuzzy_score(prod, query_normalized, is_combo_query)
                if score > 30:  # threshold
                    all_results[prod.id] = {
                        "product": prod,
                        "score": score,
                        "is_combo": False,
                        "components": []
                    }
        
        # Sắp xếp theo score
        ranked = sorted(
            all_results.values(),
            key=lambda x: (-x["score"], x["product"].default_code or "", x["product"].name or "")
        )[:limit]
        
        # Format kết quả
        output = []
        for item in ranked:
            prod = item["product"]
            output.append({
                "id": prod.id,
                "name": prod.name,
                "default_code": prod.default_code or "",
                "barcode": prod.barcode or "",
                "uom": prod.uom_id.name or "",
                "list_price": prod.list_price,
                "commercial_price": getattr(prod.product_tmpl_id, "x_studio_gi_bn_thng_mi", 0.0) or 0.0,
                "is_combo": item["is_combo"],
                "components": item["components"],
            })
        
        return output

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
        aliases = {
            "HCM": "TSN", "TSN": "TSN", "TSNSR": "TSNSR",
            "HCM_SHOWROOM": "TSNSR", "BENCAM": "KBC",
            "KBC": "KBC", "HIENDUC": "KHD", "KHD": "KHD",
        }
        code = aliases.get(code, code)
        Wh = request.env["stock.warehouse"].sudo()
        wh = Wh.search([("code", "=", code)], limit=1)
        return wh or None

    def _get_stock_by_warehouse(self, product_ids, warehouse=None):
        """Return stock by warehouse."""
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

    def _generate_ai_response(
        self,
        user_message,
        inventory_results,
        web_results,
        config,
        parsed_entities=None,
        warehouse_code=None,
        history=None,
    ):
        """Sinh câu trả lời AI với context về combo."""
        sys_prompt = (
            "Bạn là trợ lý AI cho kho hàng HLV, hỗ trợ saler & thủ kho tra cứu nhanh.\n"
            "Nguyên tắc trả lời:\n"
            "- Ngắn gọn, thân thiện, đúng trọng tâm.\n"
            "- Nếu có danh sách sản phẩm, liệt kê dạng 1., 2., 3. và dùng **Tên sản phẩm**; mã in nghiêng _(Mã: ...)_.\n"
            "- Với sản phẩm COMBO, luôn hiển thị cả thông tin các thành phần bên trong.\n"
            "- Luôn dùng số *tồn thực tế* (onhand). Nếu có theo kho, hiển thị dạng `TSN: 3, KBC: 2`.\n"
            "- Tránh lặp từ; nếu dữ liệu rõ, không cần rào trước đón sau.\n"
            "- Kết thúc bằng một câu hỏi ngắn để tiếp tục hỗ trợ."
        )

        def num(n):
            try:
                return int(n or 0)
            except Exception:
                return 0

        ctx_lines = []
        if parsed_entities:
            ctx_lines.append(f"[THÔNG TIN TRUY VẤN] {json.dumps(parsed_entities, ensure_ascii=False)}")
        if warehouse_code:
            ctx_lines.append(f"[KHO ƯU TIÊN] {warehouse_code}")

        if inventory_results:
            ctx_lines.append("DỮ LIỆU TỒN KHO (Tồn thực tế):")
            for idx, item in enumerate(inventory_results, start=1):
                name = item.get("name") or ""
                code = item.get("default_code") or ""
                uom = item.get("uom") or ""
                onhand_total = num(item.get("qty_onhand"))
                by_wh = item.get("by_warehouse") or {}
                parts = [f"{k}: {num(v)}" for k, v in by_wh.items() if num(v) > 0]
                
                line = f"{idx}. **{name}**"
                if code:
                    line += f" _(Mã: {code})_"
                line += f" — **{onhand_total} {uom}**"
                if parts:
                    line += " — theo kho: " + ", ".join(parts)
                
                # Hiển thị thông tin combo
                if item.get("is_combo"):
                    line += " — **[COMBO]**"
                    if item.get("components"):
                        comps = []
                        for c in item["components"]:
                            cname = c.get("name") or ""
                            ccode = c.get("default_code") or ""
                            cqty = c.get("qty", 1)
                            comp_str = f"{cqty}x {cname}"
                            if ccode:
                                comp_str += f" _(Mã: {ccode})_"
                            comps.append(comp_str)
                        if comps:
                            line += "\n   Thành phần: " + "; ".join(comps)
                
                ctx_lines.append(line)
        else:
            ctx_lines.append("Không tìm thấy sản phẩm phù hợp trong kho.")

        if web_results and config.get("web_search_enabled"):
            ctx_lines.append("Tham khảo trên web:")
            for w in web_results[:3]:
                title = w.get("title", "")
                price = w.get("price", "")
                link = w.get("link", "")
                ctx_lines.append(f"- {title} — {price} ({link})")

        ctx_lines.append("Hãy kết thúc bằng 1 câu hỏi ngắn để tiếp tục hỗ trợ.")
        context_block = "\n".join(ctx_lines)

        messages = [{"role": "system", "content": sys_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "assistant", "content": context_block})
        messages.append({"role": "user", "content": user_message})

        text = self._call_openai(messages, config)
        if not text:
            text = (
                "Mình đã tổng hợp tồn thực tế như trên. Bạn muốn xem chi tiết ở kho nào, "
                "hoặc mình so sánh thêm mẫu tương đương không ạ?"
            )
        return text

    def _extract_entities_local(self, text: str):
        """Extract entities từ text (fallback)."""
        t = _norm(text or "")
        frags = []
        
        if "+" in t:
            frags = [s.strip() for s in t.split("+") if s.strip()]
        
        tokens = re.findall(r"[A-Za-z0-9\-_/\.]+", t)
        for tok in tokens:
            if len(tok) >= 2 and tok not in frags:
                frags.append(tok)

        wh_hint = None
        lower = t.lower()
        if "tân sơn nhì" in lower or "tsn" in lower:
            wh_hint = "TSN"
        if "showroom" in lower or "tsnsr" in lower:
            wh_hint = "TSNSR"
        if "bến cam" in lower or "kbc" in lower:
            wh_hint = "KBC"
        if "hiền đức" in lower or "khd" in lower:
            wh_hint = "KHD"

        qty = None
        m = re.search(r"\b(\d+)\s*(cai|cái|pcs|piece|chiếc)?\b", lower)
        if m:
            try:
                qty = int(m.group(1))
            except Exception:
                qty = None

        return {"sku_fragments": frags, "warehouse_hint": wh_hint, "quantity": qty}

    def _search_web(self, query):
        """Placeholder web search."""
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
        """Handle chatbot message with conversation history."""
        try:
            # Parse message
            if request.httprequest.mimetype == "application/json":
                try:
                    data = request.jsonrequest or {}
                except Exception:
                    data = {}
                user_message = _norm(data.get("message") or "")
                user_message = re.sub(r"([A-Za-z])\s+(\d)", r"\1\2", user_message)
                user_message = re.sub(r"(\d)\s+([A-Za-z])", r"\1\2", user_message)
            else:
                user_message = _norm(request.params.get("message") or kw.get("message") or "")

            if not user_message:
                return request.make_response(
                    json.dumps({"success": False, "error": "Empty message"}),
                    headers=[("Content-Type", "application/json")]
                )

            cfg = self._get_chatbot_config()
            if not cfg["enabled"]:
                return request.make_response(
                    json.dumps({"success": False, "error": "Chatbot is not enabled"}),
                    headers=[("Content-Type", "application/json")]
                )
            if not cfg["api_key"]:
                return request.make_response(
                    json.dumps({"success": False, "error": "OpenAI API key not configured"}),
                    headers=[("Content-Type", "application/json")]
                )

            # Reset command
            if user_message.strip().lower() in {"reset", "xoa", "clear"}:
                request.session["chatbot_history"] = []
                payload = {
                    "success": True,
                    "response": "Đã xoá lịch sử cuộc trò chuyện. Mình có thể giúp gì tiếp cho bạn?",
                    "inventory_results": [],
                    "web_results": [],
                    "parsed": {},
                    "warehouse": None,
                }
                return request.make_response(json.dumps(payload), headers=[("Content-Type", "application/json")])

            # Parse local entities
            ent_local = self._extract_entities_local(user_message)
            wh = self._find_warehouse(ent_local.get("warehouse_hint")) if ent_local.get("warehouse_hint") else None

            # Flexible product search
            products = self._flexible_product_search(user_message, limit=20)

            # Get stock
            inv = []
            web_results = []
            stock_map = {}
            if products:
                ids = [p["id"] for p in products]
                stock_map = self._get_stock_by_warehouse(ids, warehouse=wh)

            for p in (products or []):
                per_wh_struct = stock_map.get(p["id"], {})
                total_onhand = sum(v.get("onhand", 0.0) for v in per_wh_struct.values()) if per_wh_struct else 0.0
                total_reserved = sum(v.get("reserved", 0.0) for v in per_wh_struct.values()) if per_wh_struct else 0.0
                total_available = sum(v.get("available", 0.0) for v in per_wh_struct.values()) if per_wh_struct else 0.0
                by_wh_onhand = {k: float(v.get("onhand", 0.0)) for k, v in per_wh_struct.items()}

                inv.append({
                    "id": p["id"],
                    "name": p["name"],
                    "default_code": p["default_code"],
                    "uom": p["uom"],
                    "list_price": p["list_price"],
                    "commercial_price": p["commercial_price"],
                    "qty_onhand": total_onhand,
                    "qty_reserved": total_reserved,
                    "qty_available": total_available,
                    "by_warehouse": by_wh_onhand,
                    "is_combo": p.get("is_combo", False),
                    "components": p.get("components", []),
                })

            # Build parsed info
            parsed = {
                "sku_fragments": ent_local.get("sku_fragments"),
                "warehouse_hint": ent_local.get("warehouse_hint"),
                "quantity": ent_local.get("quantity"),
            }

            # Conversation history
            session = request.session
            history = session.get("chatbot_history", [])
            if len(history) > 10:
                history = history[-10:]
            history.append({"role": "user", "content": user_message})

            # Generate AI response
            ai_text = self._generate_ai_response(
                user_message=user_message,
                inventory_results=inv,
                web_results=web_results,
                config=cfg,
                parsed_entities=parsed,
                warehouse_code=(wh.code if wh else None),
                history=history,
            )

            # Save response to history
            if ai_text:
                history.append({"role": "assistant", "content": ai_text})
            if len(history) > 10:
                history = history[-10:]
            session["chatbot_history"] = history

            payload = {
                "success": True,
                "response": ai_text,
                "inventory_results": inv,
                "web_results": web_results if cfg.get("web_search_enabled") else [],
                "parsed": parsed,
                "warehouse": (wh.code if wh else None),
            }
            return request.make_response(json.dumps(payload), headers=[("Content-Type", "application/json")])

        except Exception as e:
            _logger.exception("Chatbot error")
            return request.make_response(
                json.dumps({"success": False, "error": str(e)}),
                headers=[("Content-Type", "application/json")]
            )