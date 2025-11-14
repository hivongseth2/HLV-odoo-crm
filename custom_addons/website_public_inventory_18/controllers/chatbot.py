# -*- coding: utf-8 -*-
import json
import re
import logging

from odoo import http
from odoo.http import request
from odoo.osv import expression

_logger = logging.getLogger(__name__)

# ============================
# Utils (normalize text)
# ============================

def _norm(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


# ============================
# AI AGENT (Responses API + Odoo)
# ============================

class AIChatAgent(object):
    """
    Agent AI cho kho HLV:
    - Bước 1: Dùng Responses API + Structured Output để phân tích truy vấn.
    - Bước 2: Dùng Odoo ORM để search sản phẩm, lấy tồn kho.
    - Bước 3: Dùng Responses API để soạn câu trả lời thân thiện, có format.
    """

    def __init__(self, env, config):
        self.env = env
        self.config = config

    # -------- OpenAI client (Responses API) --------
    def _get_client(self):
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("Python package 'openai' chưa được cài đặt. Hãy: pip install openai")

        api_key = self.config.get("api_key") or ""
        if not api_key:
            raise RuntimeError("Chưa cấu hình OpenAI API key")
        return OpenAI(api_key=api_key)

    # -------- STEP 1: Phân tích truy vấn bằng Structured Outputs --------
    def analyze_query(self, user_message: str) -> dict:
        """
        Gọi Responses API để bóc tách:
        - action: search_product / smalltalk / help / unknown
        - normalized_query: text đã chuẩn hóa
        - sku_candidates: list mã khả nghi (FHIW2F12, M18B5, 48-22-2182…)
        - warehouse_hint: TSN / KBC / TSNSR / KHD / None
        - quantity: số lượng (nếu có)
        - allow_web_search: có cho phép search web không
        """
        client = self._get_client()

        schema = {
            "type": "json_schema",
            "name": "query_analysis",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search_product", "smalltalk", "help", "unknown"],
                    },
                    "normalized_query": {"type": "string"},
                    "sku_candidates": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "warehouse_hint": {
                        "type": ["string", "null"]
                    },
                    "quantity": {
                        "type": ["number", "null"]
                    },
                    "allow_web_search": {
                        "type": "boolean"
                    }
                },
                "required": [
                    "action",
                    "normalized_query",
                    "sku_candidates",
                    "warehouse_hint",
                    "quantity",
                    "allow_web_search",
                ],
                "additionalProperties": False,
            },
        }

        instructions = (
            "Bạn là bộ phân tích truy vấn cho kho HLV.\n"
            "Nhiệm vụ: Đọc câu hỏi của user, trích xuất thông tin thành JSON đúng schema.\n"
            "- Nếu user muốn tra mã hàng / sản phẩm / tồn kho / giá: action = 'search_product'.\n"
            "- Nếu chỉ chào hỏi, nói chuyện phiếm: action = 'smalltalk'.\n"
            "- Nếu hỏi cách dùng chatbot: action = 'help'.\n"
            "- Nếu không rõ: action = 'unknown'.\n"
            "- sku_candidates: liệt kê các chuỗi có khả năng là mã SP (chứa chữ + số, như FHIW2F12, M18B5, 48-22-2182...).\n"
            "- warehouse_hint: map về 1 trong: 'TSN', 'TSNSR', 'KBC', 'KHD' nếu user có nhắc khu vực/kho, nếu không thì null.\n"
            "- quantity: nếu user có nói số lượng (vd: 10 cái, 5 bộ...), ghi số; nếu không thì null.\n"
            "- allow_web_search: true nếu user đang hỏi thông tin thị trường / giá tham khảo ngoài kho; ngược lại false.\n"
            "Chỉ xuất JSON, không giải thích thêm."
        )

        try:
            resp = client.responses.create(
                model=self.config["model"],
                instructions=instructions,
                input=user_message,
                text={"format": schema},
                temperature=0,
                max_output_tokens=int(self.config.get("max_tokens", 400)),
            )
            raw = resp.output_text or "{}"
            try:
                parsed = json.loads(raw)
            except Exception:
                _logger.warning("Cannot parse query_analysis JSON, raw=%s", raw)
                parsed = {}
        except Exception as e:
            _logger.error("Error calling Responses API (analyze_query): %s", e)
            parsed = {}

        # Fallback an toàn
        if not isinstance(parsed, dict):
            parsed = {}
        parsed.setdefault("action", "search_product")
        parsed.setdefault("normalized_query", user_message)
        parsed.setdefault("sku_candidates", [])
        parsed.setdefault("warehouse_hint", None)
        parsed.setdefault("quantity", None)
        parsed.setdefault("allow_web_search", False)

        return parsed

    # -------- STEP 2a: Map kho từ hint --------
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
        Wh = self.env["stock.warehouse"].sudo()
        wh = Wh.search([("code", "=", code)], limit=1)
        return wh or None

    def _allowed_warehouses(self):
        Wh = self.env["stock.warehouse"].sudo()
        ids_raw = self.config.get("allowed_warehouse_ids") or ""
        ids = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
        if ids:
            whs = Wh.browse(ids).exists()
            if whs:
                return whs
        return Wh.search([])

    # -------- STEP 2b: Search product bằng Odoo ORM (cách mới, đơn giản hơn) --------
    def search_products(self, query_info: dict, limit=20):
        Product = self.env["product.product"].sudo()
        normalized_query = _norm(query_info.get("normalized_query") or "")
        sku_candidates = query_info.get("sku_candidates") or []

        codes = [c.strip() for c in sku_candidates if c and c.strip()]
        products = Product.browse()

        # ===== 1) Nếu có sku_candidates => ưu tiên search theo mã =====
        if codes:
            domain = []
            for code in codes:
                code = code.strip()
                like_code = "%%%s%%" % code.replace(" ", "%")

                # sub-domain cho từng code:
                # (default_code ilike code) OR (barcode ilike code) OR (name ilike %code%)
                sub_domain = [
                    "|", "|",
                    ("default_code", "ilike", code),
                    ("barcode", "ilike", code),
                    ("name", "ilike", like_code),
                ]

                # OR nhiều sub_domain lại với nhau
                domain = expression.OR([domain, sub_domain]) if domain else sub_domain

            products = Product.search(domain, limit=limit)

        # ===== 2) Nếu không có hoặc không tìm được => fallback theo normalized_query =====
        if not products and normalized_query:
            q = normalized_query
            like_name = "%%%s%%" % q.replace(" ", "%")
            domain = [
                "|", "|",
                ("default_code", "ilike", q),
                ("barcode", "ilike", q),
                ("name", "ilike", like_name),
            ]
            products = Product.search(domain, limit=limit)

        return products

    # -------- STEP 2c: Lấy tồn kho theo kho --------
    def _get_stock_by_warehouse(self, product_ids, warehouse=None):
        Quant = self.env["stock.quant"].sudo()
        Loc = self.env["stock.location"].sudo()

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

    # -------- STEP 3: Gọi Responses API để soạn câu trả lời --------
    def generate_answer(
        self,
        user_message: str,
        products,
        stock_map: dict,
        parsed: dict,
        warehouse,
        history=None,
    ) -> str:
        client = self._get_client()

        sys_prompt = (
            "Bạn là trợ lý AI cho kho hàng HLV, hỗ trợ saler & thủ kho tra cứu nhanh.\n"
            "Nguyên tắc trả lời:\n"
            "- Ngắn gọn, thân thiện, đúng trọng tâm.\n"
            "- Nếu có danh sách sản phẩm, liệt kê dạng 1., 2., 3. và dùng **Tên sản phẩm**; "
            "mã in nghiêng _(Mã: ...)_.\n"
            "- Luôn dùng số *tồn thực tế* (available = onhand - reserved). Hiển thị theo kho: `TSN: 3, KBC: 2`.\n"
            "- Nếu không tìm thấy sản phẩm: hướng dẫn user gửi thêm mã, hình, hoặc mô tả rõ hơn.\n"
            "- Kết thúc bằng một câu hỏi ngắn để tiếp tục hỗ trợ.\n"
        )

        def num(x):
            try:
                return int(x or 0)
            except Exception:
                return 0

        # Tạo context về kết quả tồn kho để AI dựa vào
        ctx_lines = []
        ctx_lines.append(f"[THÔNG TIN TRUY VẤN PHÂN TÍCH] {json.dumps(parsed, ensure_ascii=False)}")
        if warehouse:
            ctx_lines.append(f"[KHO ƯU TIÊN] {warehouse.code} ({warehouse.name})")

        if products:
            ctx_lines.append("DỮ LIỆU TỒN KHO (available = onhand - reserved):")
            for idx, p in enumerate(products, start=1):
                wh_data = stock_map.get(p.id, {}) or {}
                total_onhand = sum(v.get("onhand", 0.0) for v in wh_data.values())
                total_reserved = sum(v.get("reserved", 0.0) for v in wh_data.values())
                total_available = sum(v.get("available", 0.0) for v in wh_data.values())
                parts = [f"{k}: {num(v.get('available', 0.0))}" for k, v in wh_data.items() if num(v.get("available", 0.0)) > 0]

                line = f"{idx}. **{p.name}**"
                if p.default_code:
                    line += f" _(Mã: {p.default_code})_"
                if p.uom_id:
                    line += f" — **{num(total_available)} {p.uom_id.name} available**"
                else:
                    line += f" — **{num(total_available)} available**"
                if parts:
                    line += " — theo kho: " + ", ".join(parts)
                ctx_lines.append(line)
        else:
            ctx_lines.append("Không tìm thấy sản phẩm phù hợp trong kho với truy vấn hiện tại.")

        ctx_lines.append("Hãy dựa trên dữ liệu trên để trả lời user.")
        inventory_context = "\n".join(ctx_lines)

        # Chuẩn bị lịch sử hội thoại (nếu có)
        conversation = []
        if history:
            # history đã là list[{role, content}] từ session
            conversation.extend(history)
        # Thêm context kỹ thuật như 1 message assistant
        conversation.append({"role": "assistant", "content": inventory_context})
        # Thêm câu hỏi mới của user
        conversation.append({"role": "user", "content": user_message})

        try:
            resp = client.responses.create(
                model=self.config["model"],
                instructions=sys_prompt,
                input=conversation,
                temperature=float(self.config.get("temperature", 0.2)),
                max_output_tokens=int(self.config.get("max_tokens", 600)),
            )
            text = resp.output_text or ""
        except Exception as e:
            _logger.error("Error calling Responses API (generate_answer): %s", e)
            text = ""

        if not text:
            text = (
                "Mình đã xem tồn kho theo truy vấn của bạn như trên. "
                "Bạn muốn xem chi tiết kho nào, hay mình gợi ý thêm sản phẩm tương đương không ạ?"
            )
        return text

    # -------- Orchestrator: chạy full pipeline cho 1 message --------
    def handle_message(self, user_message: str, history=None):
        parsed = self.analyze_query(user_message)
        action = parsed.get("action") or "search_product"

        # Nếu chỉ smalltalk / help → không cần động tới DB
        if action in ("smalltalk", "help", "unknown"):
            # Gọi 1 lần Responses để trả lời tự do
            client = self._get_client()
            instructions = (
                "Bạn là trợ lý AI thân thiện của kho HLV. "
                "Nếu user chỉ chào hỏi hoặc hỏi cách dùng, hãy trả lời ngắn gọn, dễ hiểu."
            )
            try:
                resp = client.responses.create(
                    model=self.config["model"],
                    instructions=instructions,
                    input=user_message,
                    temperature=float(self.config.get("temperature", 0.4)),
                    max_output_tokens=int(self.config.get("max_tokens", 300)),
                )
                ai_text = resp.output_text or "Chào bạn, mình là trợ lý kho HLV. Bạn cần tra cứu mã hàng hay tồn kho nào ạ?"
            except Exception as e:
                _logger.error("Error calling Responses API (smalltalk/help): %s", e)
                ai_text = "Chào bạn, hiện mình đang gặp chút sự cố kết nối AI. Bạn có thể thử lại sau nhé."
            return {
                "response": ai_text,
                "inventory": [],
                "parsed": parsed,
                "warehouse": None,
            }

        # action = search_product
        warehouse_hint = parsed.get("warehouse_hint")
        wh = self._find_warehouse(warehouse_hint) if warehouse_hint else None

        products = self.search_products(parsed, limit=20)
        inv_list = []
        stock_map = {}

        if products:
            ids = products.ids
            stock_map = self._get_stock_by_warehouse(ids, warehouse=wh)

            for p in products:
                wh_data = stock_map.get(p.id, {}) or {}
                total_onhand = sum(v.get("onhand", 0.0) for v in wh_data.values())
                total_reserved = sum(v.get("reserved", 0.0) for v in wh_data.values())
                total_available = sum(v.get("available", 0.0) for v in wh_data.values())

                inv_list.append({
                    "id": p.id,
                    "name": p.name,
                    "default_code": p.default_code or "",
                    "uom": p.uom_id.name if p.uom_id else "",
                    "list_price": p.list_price,
                    "commercial_price": getattr(p.product_tmpl_id, "x_studio_gi_bn_thng_mi", 0.0) or 0.0,
                    "qty_onhand": total_onhand,
                    "qty_reserved": total_reserved,
                    "qty_available": total_available,
                    "by_warehouse": {k: float(v.get("available", 0.0)) for k, v in wh_data.items()},
                })

        ai_text = self.generate_answer(
            user_message=user_message,
            products=products,
            stock_map=stock_map,
            parsed=parsed,
            warehouse=wh,
            history=history,
        )

        return {
            "response": ai_text,
            "inventory": inv_list,
            "parsed": parsed,
            "warehouse": wh.code if wh else None,
        }


# ============================
# CONTROLLER
# ============================

class ChatbotController(http.Controller):
    # ===== CONFIG =====
    def _get_chatbot_config(self):
        """Read settings from System Parameters."""
        param = request.env["ir.config_parameter"].sudo()
        return {
            "enabled": param.get_param("website_public_inventory_18.chatbot_enabled", default=False) in (True, "True", "1", "true"),
            "api_key": param.get_param("website_public_inventory_18.openai_api_key", default=""),
            # model đã chuyển sang Responses API (ví dụ: gpt-4.1-mini / gpt-5)
            "model": param.get_param("website_public_inventory_18.openai_model", default="gpt-4.1-mini"),
            "max_tokens": int(param.get_param("website_public_inventory_18.chatbot_max_tokens", default=600)),
            "temperature": float(param.get_param("website_public_inventory_18.chatbot_temperature", default=0.2)),
            "web_search_enabled": param.get_param("website_public_inventory_18.web_search_enabled", default=True) in (True, "True", "1", "true"),
            "allowed_warehouse_ids": param.get_param("website_public_inventory_18.allowed_warehouse_ids", default=""),
        }

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
        """Handle chatbot message with conversation history (agentic version)."""
        try:
            # Parse message
            if request.httprequest.mimetype == "application/json":
                try:
                    data = request.jsonrequest or {}
                except Exception:
                    data = {}
                user_message = _norm(data.get("message") or "")
                # Ghép chữ + số dính liền (M18 B5 -> M18B5)
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

            # Conversation history (giữ tối đa 10 message gần nhất)
            session = request.session
            history = session.get("chatbot_history", [])
            if len(history) > 10:
                history = history[-10:]
            history.append({"role": "user", "content": user_message})

            # Dùng Agent mới
            agent = AIChatAgent(request.env, cfg)
            result = agent.handle_message(user_message=user_message, history=history)

            ai_text = result.get("response")
            inv = result.get("inventory") or []
            parsed = result.get("parsed") or {}
            wh_code = result.get("warehouse")

            # Lưu history
            if ai_text:
                history.append({"role": "assistant", "content": ai_text})
            if len(history) > 10:
                history = history[-10:]
            session["chatbot_history"] = history

            payload = {
                "success": True,
                "response": ai_text,
                "inventory_results": inv,
                "web_results": [],  # sau này nếu dùng web_search thật thì thêm vào
                "parsed": parsed,
                "warehouse": wh_code,
            }
            return request.make_response(json.dumps(payload), headers=[("Content-Type", "application/json")])

        except Exception as e:
            _logger.exception("Chatbot error")
            return request.make_response(
                json.dumps({"success": False, "error": str(e)}),
                headers=[("Content-Type", "application/json")]
            )
