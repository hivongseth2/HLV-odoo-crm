# -*- coding: utf-8 -*-
import logging
import json
from odoo import models, fields, api, _
from odoo.exceptions import UserError

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

_logger = logging.getLogger(__name__)

class HlvChatgptSession(models.Model):
    _name = 'hlv.chatgpt.session'
    _description = 'Phiên Chat AI'
    _rec_name = 'name'
    _order = 'last_activity desc'
    
    state = fields.Selection([
        ('new', 'Mới'),
        ('active', 'Đang hoạt động'),
        ('archived', 'Lưu trữ')
    ], default='new', string='Trạng thái')
    # ======================================

    name = fields.Char(string='Chủ đề', default='Cuộc hội thoại mới', required=True)
    user_id = fields.Many2one('res.users', string='Người tạo', default=lambda self: self.env.user)
    last_activity = fields.Datetime(string='Hoạt động cuối', default=fields.Datetime.now)
    
    # Quản lý trạng thái Agent hiện tại (Router hay Chuyên gia)
    current_agent = fields.Selection([
        ('router', 'Router (Tổng đài)'),
        ('stock', 'Stock Expert (Kho)'),
        ('naming', 'Naming Expert (Đặt tên)')
    ], default='router', string="Đang chat với")

    message_ids = fields.One2many('hlv.chatgpt.message', 'session_id', string='Nội dung hội thoại')
    input_text = fields.Text(string='Nhập tin nhắn...')

    # =================================================================================
    # 1. CÁC HÀM TOOL ODOO (SEARCH LOGIC)
    # =================================================================================
    def _execute_check_product_existence(self, keyword):
        _logger.info("🔧 Check Existence: %s", keyword)
        if not keyword: return json.dumps({"error": "Thiếu từ khóa"})
        
        products = self.env['product.product'].sudo().with_context(active_test=False).search([
            '|', ('default_code', 'ilike', keyword), ('name', 'ilike', keyword)
        ], limit=5)
        
        if not products: 
            return json.dumps({"status": "not_found", "message": f"Chưa có mã nào khớp '{keyword}'."})
        
        return json.dumps([{
            "name": p.name, 
            "code": p.default_code, 
            "status": "Active" if p.active else "Archived"
        } for p in products], ensure_ascii=False)

    def _execute_search_product_stock(self, keyword):
        """Logic Search V3: Tokenize + Score Sorting"""
        _logger.info("🔧 Search Stock: %s", keyword)
        if not keyword: return json.dumps({"error": "Thiếu từ khóa"})

        # Stop words removal
        stop_words = ["thường", "máy", "cái", "con", "cây", "bộ", "khoan", "pin", "sạc", "thân", "body", "bare", "search", "tìm", "kiểm", "tra", "tồn", "kho", "giá"]
        keyword_clean = keyword.lower()
        for w in stop_words: keyword_clean = keyword_clean.replace(f" {w} ", " ").replace(f"{w} ", "")
        keyword_clean = keyword_clean.strip() or keyword

        # Search
        tokens = keyword_clean.split()
        domain = [('active', '=', True)]
        for token in tokens:
            domain += ['|', '|', '|', ('name', 'ilike', token), ('default_code', 'ilike', token), ('barcode', 'ilike', token), ('description_sale', 'ilike', token)]
        
        products = self.env['product.product'].sudo().search(domain, limit=15)
        
        if not products: 
            return json.dumps({"status": "empty", "message": f"Không tìm thấy '{keyword_clean}'"})

        # Sort & Format
        result = []
        for p in products:
            score = 0
            if p.qty_available > 0: score += 1000
            if keyword_clean in p.name.lower(): score += 100
            if "combo" in p.name.lower() and "combo" not in keyword_clean: score -= 50
            
            result.append({
                "name": p.name, "code": p.default_code, "price": p.list_price, 
                "qty": p.qty_available, "uom": p.uom_id.name, "score": score
            })
        
        result.sort(key=lambda x: x['score'], reverse=True)
        for item in result: del item['score']
        
        return json.dumps(result, ensure_ascii=False)

    # =================================================================================
    # 2. XỬ LÝ GỬI NHẬN (ACTION BUTTON)
    # =================================================================================
    def action_send_message(self):
        self.ensure_one()
        if not self.input_text: raise UserError("Vui lòng nhập nội dung.")

        # Lưu tin nhắn User
        self.env['hlv.chatgpt.message'].create({
            'session_id': self.id, 'role': 'user', 'content': self.input_text
        })
        
        user_query = self.input_text
        self.input_text = ""

        # Gọi AI
        ai_reply = self._call_openai_api(user_query)

        # Lưu tin nhắn AI
        self.env['hlv.chatgpt.message'].create({
            'session_id': self.id, 'role': 'assistant', 'content': ai_reply
        })
        self.last_activity = fields.Datetime.now()

    # =================================================================================
    # 3. CORE LOGIC: CHẠY PROMPT LOOP
    # =================================================================================
    def _run_prompt_loop(self, client, prompt_id, messages_history):
        """Vòng lặp: Gọi API -> Check Tool -> Chạy Tool -> Gọi lại API"""
        
        for _ in range(3): # Max 3 turns to avoid loops
            try:
                _logger.info("🚀 Calling Prompt ID: %s", prompt_id)
                response = client.responses.create(
                    model="gpt-4o",
                    prompt={"id": prompt_id},
                    input=messages_history,
                )
                
                # Parse Response (Hỗ trợ cấu trúc mới nhất của OpenAI)
                output_msg = None
                if hasattr(response, 'choices'): output_msg = response.choices[0].message
                elif hasattr(response, 'output'): 
                    for item in response.output:
                        if item.type == 'message': 
                            output_msg = item
                            break
                
                if not output_msg: return {"status": "error", "text": "Empty response"}

                # Check Tool Calls
                tool_calls = getattr(output_msg, 'tool_calls', None)
                
                if tool_calls:
                    # Append AI message (with tool calls) to history
                    messages_history.append(output_msg)
                    
                    for tool in tool_calls:
                        fname = tool.function.name
                        args = json.loads(tool.function.arguments)
                        _logger.info("⚡ Executing Tool: %s", fname)

                        # --- ROUTER LOGIC ---
                        if fname == "handoff_to_stock_agent":
                            return {"status": "handoff", "target": "stock"}
                        elif fname == "handoff_to_naming_agent":
                            return {"status": "handoff", "target": "naming"}
                        
                        # --- STOCK LOGIC ---
                        elif fname == "search_product_stock":
                            tool_res = self._execute_search_product_stock(args.get('keyword'))
                        elif fname == "check_product_existence":
                            tool_res = self._execute_check_product_existence(args.get('keyword'))
                        else:
                            tool_res = json.dumps({"error": "Function unknown"})

                        # Append Tool Output to history
                        messages_history.append({
                            "role": "tool", "tool_call_id": tool.id, "content": tool_res
                        })
                    
                    # Continue loop to send tool outputs back to AI
                    continue
                
                else:
                    # Không có tool call -> Đây là câu trả lời cuối cùng (Text)
                    final_text = output_msg.content
                    
                    if isinstance(final_text, list):
                        # Lấy phần tử đầu tiên của list
                        first_item = final_text[0]
                        
                        # Kiểm tra xem có thuộc tính .text không
                        if hasattr(first_item, 'text'):
                            text_content = first_item.text
                            # FIX LỖI: Kiểm tra xem .text là object (có .value) hay là string
                            if hasattr(text_content, 'value'):
                                final_text = text_content.value
                            else:
                                final_text = str(text_content)
                        else:
                            # Fallback nếu cấu trúc lạ
                            final_text = str(first_item)
                    
                    return {"status": "done", "text": final_text}

            except Exception as e:
                _logger.exception("OpenAI API Error")
                return {"status": "error", "text": str(e)}
        
        return {"status": "error", "text": "Timeout loop"}

    def _call_openai_api(self, query):
        if not OpenAI: return "Lỗi: Chưa cài openai."
        config = self.env['hlv.chatgpt.config'].get_config()
        if not config: return "Lỗi: Chưa cấu hình."

        client = OpenAI(api_key=config.api_key)

        # 1. Build History (Context)
        history = []
        for msg in self.message_ids:
            history.append({"role": msg.role, "content": msg.content or ""})
        
        # 2. Determine Prompt ID
        # Logic: Mặc định dùng Router. Nếu đang ở mode chuyên gia thì dùng chuyên gia.
        target_id = config.router_prompt_id
        if self.current_agent == 'stock': target_id = config.stock_prompt_id
        elif self.current_agent == 'naming': target_id = config.naming_prompt_id

        # 3. Run Loop
        result = self._run_prompt_loop(client, target_id, history)

        # 4. Handle Result
        if result['status'] == 'done':
            return result['text']
        
        elif result['status'] == 'handoff':
            new_target = result['target']
            self.current_agent = new_target # Switch Agent
            _logger.info("🔀 Handoff to: %s", new_target)
            
            # Switch Prompt ID
            new_prompt_id = config.stock_prompt_id if new_target == 'stock' else config.naming_prompt_id
            
            # Run again immediately with new Prompt (Send the same history)
            # Note: The history already contains the user query, so we just run the new prompt on it
            final_res = self._run_prompt_loop(client, new_prompt_id, history)
            
            if final_res['status'] == 'done': return final_res['text']
            
        return "Hệ thống đang bận."

class HlvChatgptMessage(models.Model):
    _name = 'hlv.chatgpt.message'
    _description = 'Chi tiết tin nhắn'
    _order = 'create_date asc'

    session_id = fields.Many2one('hlv.chatgpt.session', string='Phiên chat', ondelete='cascade')
    role = fields.Selection([('user', 'Bạn'), ('assistant', 'AI'), ('tool', 'Tool')], string='Role', required=True)
    content = fields.Text(string='Nội dung')