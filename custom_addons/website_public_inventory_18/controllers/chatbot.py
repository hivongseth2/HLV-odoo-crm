# -*- coding: utf-8 -*-
import json
import re
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# ============================
# Utils (normalize text)
# ============================

def _norm(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


# ============================
# AI AGENT (Responses API + Vector Store + Odoo)
# ============================

class AIChatAgent(object):
    """
    Agent AI cho kho HLV (luồng mới):
    - Bước 1: Dùng Responses API + file_search (vector store product) để phân tích truy vấn,
      tìm ra action + danh sách mã sản phẩm nên kiểm tra.
    - Bước 2: Dùng Odoo ORM để lấy tồn kho + giá theo các mã đó.
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

    # -------- STEP 1: Phân tích truy vấn + dùng file_search trên vector store --------
    def analyze_query(self, user_message: str) -> dict:
        """
        Gọi Responses API để bóc tách truy vấn, sử dụng file_search (vector store product) làm kiến thức nền.

        Output mong muốn:
        - action: 'search_product' / 'smalltalk' / 'help' / 'unknown'
        - normalized_query: text đã chuẩn hóa
        - product_codes: list mã sản phẩm nên kiểm tra tồn (ưu tiên lấy từ vector store)
        - warehouse_hint: TSN / KBC / TSNSR / KHD / None
        - quantity: số lượng (nếu có)
        - allow_web_search: có cho phép search web không
        """
        client = self._get_client()

        vector_store_id = self.config.get("product_vector_store_id") or ""

        # JSON schema cho Structured Output
        schema = {
            "type": "json_schema",
            "name": "catalog_query_analysis",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search_product", "smalltalk", "help", "unknown"],
                    },
                    "normalized_query": {"type": "string"},
                    "product_codes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Danh sách mã sản phẩm chuẩn (default_code) nên kiểm tra tồn kho.",
                    },
                    "warehouse_hint": {
                        "type": "string",
                        "description": "Mã kho gợi ý (TSN, KBC, TSNSR, KHD) nếu user có nhắc, nếu không thì chuỗi rỗng.",
                    },
                    "quantity": {
                        "type": "number",
                        "description": "Số lượng nếu user có đề cập, nếu không thì 0.",
                    },
                    "allow_web_search": {
                        "type": "boolean",
                        "description": "true nếu user đang hỏi thông tin thị trường / giá tham khảo ngoài kho.",
                    },
                },
                # Để an toàn, chỉ bắt buộc 3 field chính, còn lại optional
                "required": ["action", "normalized_query", "product_codes"],
                "additionalProperties": False,
            },
        }

        instructions = (
            "Bạn là bộ phân tích truy vấn cho kho HLV.\n"
            "Bạn có quyền dùng tool 'file_search' để tra cứu catalog sản phẩm (mã, tên, alias...).\n"
            "Nhiệm vụ:\n"
            "- Xác định action: nếu user muốn tra sản phẩm / tồn kho / giá -> 'search_product';\n"
            "  nếu chỉ chào hỏi -> 'smalltalk'; nếu hỏi cách dùng chatbot -> 'help'; nếu không rõ -> 'unknown'.\n"
            "- normalized_query: phiên bản đã chuẩn hóa của câu hỏi.\n"
            "- product_codes: từ catalog, chọn ra các mã sản phẩm (default_code) phù hợp với câu hỏi.\n"
            "  Ưu tiên mã thân máy chính (main) hơn phụ tùng nếu cùng series.\n"
            "- warehouse_hint: nếu user có nhắc khu vực / kho (TSN, TSNSR, KBC, KHD, tân sơn nhất, bến cam...),\n"
            "  hãy map về 1 trong 'TSN', 'TSNSR', 'KBC', 'KHD'. Nếu không rõ, trả về chuỗi rỗng.\n"
            "- quantity: nếu user có nhắc số lượng (vd: 5 cái, 10 bộ...), ghi số; nếu không thì 0.\n"
            "- allow_web_search: true nếu user đang hỏi giá thị trường / thông tin tham khảo ngoài kho; ngược lại false.\n\n"
            "Chỉ xuất JSON đúng schema, không kèm giải thích."
        )

        # Chuẩn bị tools: chỉ dùng file_search ở bước phân tích
        tools = None
        if vector_store_id:
            tools = [
                {
                    "type": "file_search",
                    "vector_store_ids": [vector_store_id],
                }
            ]

        try:
            resp = client.responses.create(
                model=self.config["model"],
                instructions=instructions,
                input=user_message,
                # tools=tools if tools else None,
                **({"tools": tools} if tools else {}),
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
        parsed.setdefault("product_codes", [])
        parsed.setdefault("warehouse_hint", "")
        parsed.setdefault("quantity", 0)
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

    # -------- STEP 2b: Lấy tồn kho theo kho --------
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

    # -------- STEP 2c: Chạy inventory thực tế trên Odoo dựa trên analysis --------
    def _run_inventory_lookup(self, analysis: dict, limit: int = 20):
        """
        Dựa trên kết quả phân tích (đã dùng file_search), quyết định lấy tồn kho từ Odoo.
        Ưu tiên product_codes; nếu không có, fallback bằng normalized_query.
        """
        Product = self.env["product.product"].sudo()

        normalized_query = _norm(analysis.get("normalized_query") or "")
        product_codes = analysis.get("product_codes") or []
        warehouse_hint = analysis.get("warehouse_hint") or ""
        wh = self._find_warehouse(warehouse_hint) if warehouse_hint else None

        products = Product.browse()

        # 1) Nếu có product_codes (từ catalog) -> ưu tiên tìm theo default_code trong đó
        if product_codes:
            clean_codes = [c.strip() for c in product_codes if c and c.strip()]
            clean_codes = list(dict.fromkeys(clean_codes))  # bỏ trùng
            if clean_codes:
                products = Product.search([("default_code", "in", clean_codes)], limit=limit)

        # 2) Nếu vẫn chưa thấy gì, fallback theo normalized_query (tối thiểu vẫn có search fuzzy)
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

        if not products:
            return {
                "query": normalized_query,
                "warehouse": wh.code if wh else None,
                "items": [],
            }

        stock_map = self._get_stock_by_warehouse(products.ids, warehouse=wh)
        items = []

        for p in products:
            wh_data = stock_map.get(p.id, {}) or {}
            total_onhand = sum(v.get("onhand", 0.0) for v in wh_data.values())
            total_reserved = sum(v.get("reserved", 0.0) for v in wh_data.values())
            total_available = sum(v.get("available", 0.0) for v in wh_data.values())

            items.append({
                "id": p.id,
                "name": p.name,
                "default_code": p.default_code or "",
                "uom": p.uom_id.name if p.uom_id else "",
                "list_price": p.list_price,
                "commercial_price": getattr(p.product_tmpl_id, "x_studio_gi_bn_thng_mi", 0.0) or 0.0,
                "qty_onhand": float(total_onhand),
                "qty_reserved": float(total_reserved),
                "qty_available": float(total_available),
                "by_warehouse": {k: float(v.get("available", 0.0)) for k, v in wh_data.items()},
            })

        return {
            "query": normalized_query,
            "warehouse": wh.code if wh else None,
            "items": items,
        }

    # -------- STEP 3: Gọi Responses API để soạn câu trả lời --------
    def generate_answer(
        self,
        user_message: str,
        analysis: dict,
        inventory_payload: dict,
        history=None,
    ) -> str:
        client = self._get_client()

        sys_prompt = (
            "Bạn là trợ lý AI cho kho hàng HLV, hỗ trợ saler & thủ kho tra cứu nhanh.\n"
            "Nguyên tắc trả lời:\n"
            "- Ngắn gọn, thân thiện, đúng trọng tâm.\n"
            "- Nếu có danh sách sản phẩm, liệt kê dạng 1., 2., 3. và dùng **Tên sản phẩm**; "
            "mã in nghiêng _(Mã: ...)_.\n"
            "- Luôn dùng số *tồn thực tế* (available = onhand - reserved). "
            "Hiển thị theo kho: `TSN: 3, KBC: 2`.\n"
            "- Có thể nhắc giá bán và giá thương mại (TM) nếu có.\n"
            "- Nếu không tìm thấy sản phẩm: hướng dẫn user gửi thêm mã, hình, hoặc mô tả rõ hơn.\n"
            "- Kết thúc bằng một câu hỏi ngắn để tiếp tục hỗ trợ.\n"
        )

        def num(x):
            try:
                return int(x or 0)
            except Exception:
                return 0

        items = inventory_payload.get("items", []) or []
        wh_code = inventory_payload.get("warehouse")
        normalized_query = analysis.get("normalized_query")

        ctx_lines = []
        ctx_lines.append(f"[THÔNG TIN TRUY VẤN PHÂN TÍCH] {json.dumps(analysis, ensure_ascii=False)}")
        if wh_code:
            ctx_lines.append(f"[KHO ƯU TIÊN] {wh_code}")

        if items:
            ctx_lines.append("DỮ LIỆU TỒN KHO (available = onhand - reserved):")
            for idx, item in enumerate(items, start=1):
                name = item.get("name") or ""
                code = item.get("default_code") or ""
                uom = item.get("uom") or ""
                total_available = num(item.get("qty_available"))
                by_wh = item.get("by_warehouse") or {}
                parts = [f"{k}: {num(v)}" for k, v in by_wh.items() if num(v) > 0]

                line = f"{idx}. **{name}**"
                if code:
                    line += f" _(Mã: {code})_"
                if uom:
                    line += f" — **{total_available} {uom} available**"
                else:
                    line += f" — **{total_available} available**"
                if parts:
                    line += " — theo kho: " + ", ".join(parts)

                list_price = item.get("list_price")
                comm_price = item.get("commercial_price")
                if list_price or comm_price:
                    price_parts = []
                    if list_price:
                        price_parts.append(f"Giá niêm yết: {int(list_price):,} VND".replace(",", "."))
                    if comm_price:
                        price_parts.append(f"Giá TM: {int(comm_price):,} VND".replace(",", "."))
                    line += " — " + " | ".join(price_parts)

                ctx_lines.append(line)
        else:
            ctx_lines.append(
                "Không tìm thấy sản phẩm phù hợp trong kho với truy vấn hiện tại. "
                "Có thể mã hoặc tên sản phẩm chưa đúng với catalog."
            )

        ctx_lines.append("Hãy dựa trên dữ liệu trên để trả lời user bằng tiếng Việt.")
        inventory_context = "\n".join(ctx_lines)

        # Chuẩn bị lịch sử hội thoại (nếu có)
        conversation = []
        if history:
            conversation.extend(history)
        conversation.append({"role": "assistant", "content": inventory_context})
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
        """
        Pipeline mới:
        - Bước 1: analyze_query (có dùng file_search) -> action + product_codes + warehouse_hint...
        - Bước 2: nếu action là smalltalk/help/unknown -> trả lời trực tiếp, không cần tra tồn kho.
        - Bước 3: nếu action = search_product -> _run_inventory_lookup -> generate_answer.
        """
        # Bước 1: phân tích truy vấn
        analysis = self.analyze_query(user_message=user_message)
        action = analysis.get("action", "search_product")

        # smalltalk / help / unknown -> không cần tra tồn kho
        if action in ("smalltalk", "help", "unknown"):
            client = self._get_client()
            sys_prompt = (
                "Bạn là trợ lý AI thân thiện cho kho hàng HLV.\n"
                "- Nếu user chào hỏi / smalltalk: trả lời ngắn gọn, tự nhiên.\n"
                "- Nếu user hỏi cách dùng chatbot: giải thích cách gửi mã, tên sản phẩm, hỏi tồn kho,\n"
                "  hỏi giá, gõ 'reset' để xoá lịch sử.\n"
                "- Không cần tra tồn kho khi action không phải 'search_product'.\n"
            )
            conversation = []
            if history:
                conversation.extend(history)
            conversation.append({"role": "user", "content": user_message})

            try:
                resp = client.responses.create(
                    model=self.config["model"],
                    instructions=sys_prompt,
                    input=conversation,
                    temperature=float(self.config.get("temperature", 0.3)),
                    max_output_tokens=int(self.config.get("max_tokens", 400)),
                )
                txt = resp.output_text or "Mình có thể giúp bạn tra cứu sản phẩm và tồn kho. Bạn thử gửi mã hoặc tên sản phẩm nhé?"
            except Exception as e:
                _logger.error("Error calling Responses API (smalltalk/help): %s", e)
                txt = "Mình có thể giúp bạn tra cứu sản phẩm và tồn kho. Bạn thử gửi mã hoặc tên sản phẩm nhé?"

            return {
                "response": txt,
                "inventory": [],
                "parsed": analysis,
                "warehouse": None,
            }

        # Bước 2: action = search_product -> tra tồn kho thực tế
        inventory_payload = self._run_inventory_lookup(analysis, limit=20)

        # Bước 3: generate câu trả lời cuối cùng
        final_text = self.generate_answer(
            user_message=user_message,
            analysis=analysis,
            inventory_payload=inventory_payload,
            history=history,
        )

        return {
            "response": final_text,
            "inventory": inventory_payload.get("items", []),
            "parsed": analysis,
            "warehouse": inventory_payload.get("warehouse"),
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
            "product_vector_store_id": param.get_param("website_public_inventory_18.product_vector_store_id", ""),
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
