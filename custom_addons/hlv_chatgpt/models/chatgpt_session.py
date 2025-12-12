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
        
        # Tạo bản sao cục bộ để xử lý
        local_history = list(messages_history)

        for i in range(3): # Max 3 turns
            try:
                _logger.info("🚀 [%s] Calling Prompt ID: %s", i+1, prompt_id)
                
                response = client.responses.create(
                    model="gpt-4o",
                    prompt={"id": prompt_id},
                    input=local_history,
                )
                
                _logger.info("👉 RAW RESPONSE: %s", response)

                # --- 1. PARSE OUTPUT (HỖ TRỢ CẤU TRÚC MỚI) ---
                tool_calls_found = []
                final_text_found = ""
                
                # Kiểm tra xem có output không
                if hasattr(response, 'output'):
                    for item in response.output:
                        item_type = getattr(item, 'type', '')
                        
                        # TRƯỜNG HỢP A: Là Tool Call (như log bạn gửi)
                        if item_type == 'function_call':
                            tool_calls_found.append(item)
                            
                        # TRƯỜNG HỢP B: Là Text Message
                        elif item_type == 'message':
                            # Lấy nội dung text
                            content_list = getattr(item, 'content', [])
                            if content_list:
                                first_content = content_list[0]
                                # Cấu trúc: ResponseOutputText(text='...', ...)
                                if hasattr(first_content, 'text'):
                                    final_text_found = first_content.text
                
                # Fallback: Cấu trúc Chat Completion cũ (choices)
                elif hasattr(response, 'choices'):
                    msg = response.choices[0].message
                    if msg.tool_calls:
                        tool_calls_found = msg.tool_calls
                    else:
                        final_text_found = msg.content

                # --- 2. XỬ LÝ LOGIC ---
                
                # Nếu tìm thấy Tool Call -> Xử lý ngay
                if tool_calls_found:
                    # Append AI response vào history (Cần cẩn thận với cấu trúc append)
                    # Với endpoint responses, ta append output items trực tiếp
                    # Tuy nhiên để đơn giản cho vòng lặp, ta chỉ cần append kết quả tool
                    
                    for tool in tool_calls_found:
                        # Lấy thông tin hàm
                        # Cấu trúc ResponseFunctionToolCall: .name, .arguments (trực tiếp)
                        # Cấu trúc ChatCompletionTool: .function.name, .function.arguments
                        
                        if hasattr(tool, 'function'): # Cấu trúc cũ
                            fname = tool.function.name
                            args_str = tool.function.arguments
                            # Lưu ý: ChatCompletion dùng 'id', Stored Prompt dùng 'call_id'
                            call_id = tool.id 
                        else: # Cấu trúc mới (từ log của bạn)
                            fname = tool.name
                            args_str = tool.arguments
                            call_id = getattr(tool, 'call_id', None) or getattr(tool, 'id', None)

                        args = json.loads(args_str)
                        _logger.info("⚡ Executing Tool: %s | ID: %s", fname, call_id)

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

                        # Append Tool Output
                        local_history.append({
                            "role": "tool", 
                            "tool_call_id": call_id, # Quan trọng: Phải khớp với ID từ AI
                            "content": tool_res
                        })
                    
                    # Tiếp tục vòng lặp để gửi tool output lên
                    continue
                
                # Nếu có Text -> Trả về kết quả
                elif final_text_found:
                    return {"status": "done", "text": final_text_found}
                
                else:
                    return {"status": "error", "text": "AI không trả về nội dung text hay tool call nào."}

            except Exception as e:
                _logger.exception("OpenAI API Error")
                return {"status": "error", "text": str(e)}
        
        return {"status": "error", "text": "Timeout loop"}

    def _call_openai_api(self, query):
        if not OpenAI: return "Lỗi: Chưa cài openai."
        config = self.env['hlv.chatgpt.config'].get_config()
        if not config: return "Lỗi: Chưa cấu hình."

        client = OpenAI(api_key=config.api_key)

        # 1. Build Base History (Từ DB)
        # Chỉ lấy text chat thông thường, bỏ qua các tool call cũ để tiết kiệm token và tránh lỗi
        base_history = []
        for msg in self.message_ids:
            base_history.append({"role": msg.role, "content": msg.content or ""})
        
        # Thêm câu hỏi mới của User
        base_history.append({"role": "user", "content": query})
        
        # 2. Xác định Prompt ID ban đầu
        # Nếu đang ở chế độ Router -> Gọi Router
        # Nếu đang ở chế độ Stock -> Gọi Stock luôn (Chat tiếp)
        target_id = config.router_prompt_id
        if self.current_agent == 'stock': target_id = config.stock_prompt_id
        elif self.current_agent == 'naming': target_id = config.naming_prompt_id

        # 3. CHẠY VÒNG 1 (Với Prompt hiện tại)
        # QUAN TRỌNG: Truyền list(base_history) để tạo bản sao
        result = self._run_prompt_loop(client, target_id, list(base_history))

        # 4. XỬ LÝ KẾT QUẢ
        if result['status'] == 'done':
            return result['text']
        
        elif result['status'] == 'handoff':
            # === PHÁT HIỆN CHUYỂN HƯỚNG ===
            new_target = result['target']
            self.current_agent = new_target # Lưu trạng thái mới
            
            _logger.info("🔀 Handoff detected! Switching to: %s", new_target)
            
            # Chọn Prompt ID mới
            new_prompt_id = config.stock_prompt_id if new_target == 'stock' else config.naming_prompt_id
            
            # CHẠY VÒNG 2 (Với Prompt mới)
            # QUAN TRỌNG: Gửi lại 'base_history' sạch (chỉ chứa câu hỏi user), 
            # KHÔNG gửi kèm cái tool call handoff của Router vừa rồi.
            final_res = self._run_prompt_loop(client, new_prompt_id, list(base_history))
            
            if final_res['status'] == 'done':
                return final_res['text']
            else:
                return f"Lỗi tại Agent đích ({new_target}): {final_res.get('text')}"
            
        return f"Hệ thống bận. Lỗi: {result.get('text')}"
class HlvChatgptMessage(models.Model):
    _name = 'hlv.chatgpt.message'
    _description = 'Chi tiết tin nhắn'
    _order = 'create_date asc'

    session_id = fields.Many2one('hlv.chatgpt.session', string='Phiên chat', ondelete='cascade')
    role = fields.Selection([('user', 'Bạn'), ('assistant', 'AI'), ('tool', 'Tool')], string='Role', required=True)
    content = fields.Text(string='Nội dung')