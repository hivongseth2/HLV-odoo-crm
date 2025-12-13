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
    openai_thread_id = fields.Char(string="OpenAI Thread ID", readonly=True)
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




    def _run_assistant_workflow(self, client, assistant_id, user_query):
            """
            Chạy Workflow tự động bằng Assistants API.
            Ưu điểm: Tự động Search File -> Tự động Gọi Tool -> Tự động Trả lời.
            """
            _logger.info("🚀 Starting Workflow | Assistant: %s", assistant_id)

            # 1. QUẢN LÝ THREAD (LUỒNG CHAT)
            # Nếu session này chưa có thread_id thì tạo mới, có rồi thì dùng lại để nhớ ngữ cảnh
            thread_id = self.openai_thread_id
            if not thread_id:
                thread = client.beta.threads.create()
                self.openai_thread_id = thread.id # Lưu vào DB Odoo
                thread_id = thread.id
                _logger.info("✨ Created New Thread: %s", thread_id)
            else:
                _logger.info("🔄 Resuming Thread: %s", thread_id)

            # 2. GỬI TIN NHẮN CỦA USER VÀO THREAD
            client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=user_query
            )

            # 3. CHẠY RUN (Kích hoạt Assistant)
            run = client.beta.threads.runs.create_and_poll(
                thread_id=thread_id,
                assistant_id=assistant_id,
            )

            # 4. XỬ LÝ KẾT QUẢ (LOOP NGẦM CỦA OPENAI)
            final_response = "Hệ thống không phản hồi."

            # Nếu AI cần gọi Tool (Ví dụ: search_product_stock)
            if run.status == 'requires_action':
                tool_outputs = []
                
                # Lấy danh sách các tool nó muốn gọi
                for tool in run.required_action.submit_tool_outputs.tool_calls:
                    fname = tool.function.name
                    args_str = tool.function.arguments
                    call_id = tool.id
                    
                    try: args = json.loads(args_str)
                    except: args = {}
                    
                    _logger.info("⚡ Workflow calling Tool: %s | Args: %s", fname, args)

                    # --- GỌI HÀM ODOO CỦA BẠN ---
                    output_str = "{}"
                    if fname == "search_product_stock":
                        # Gọi lại hàm V9 xịn xò bạn đã viết
                        output_str = self._execute_search_product_stock(args.get('keyword'))
                    
                    # Đóng gói kết quả
                    tool_outputs.append({
                        "tool_call_id": call_id,
                        "output": output_str
                    })

                # Gửi kết quả Tool về lại cho OpenAI
                if tool_outputs:
                    try:
                        run = client.beta.threads.runs.submit_tool_outputs_and_poll(
                            thread_id=thread_id,
                            run_id=run.id,
                            tool_outputs=tool_outputs
                        )
                    except Exception as e:
                        return f"Lỗi khi gửi kết quả tool: {str(e)}"

            # 5. LẤY CÂU TRẢ LỜI CUỐI CÙNG
            if run.status == 'completed': 
                # Lấy tin nhắn mới nhất từ Assistant
                messages = client.beta.threads.messages.list(thread_id=thread_id, limit=1)
                if messages.data:
                    # Content trả về là 1 list, lấy text
                    for content in messages.data[0].content:
                        if hasattr(content, 'text'):
                            final_response = content.text.value
                            # Xóa citation [source] nếu cần cho sạch đẹp (Optional)
                            import re
                            final_response = re.sub(r'【.*?】', '', final_response)

            else:
                final_response = f"Workflow kết thúc với trạng thái lạ: {run.status}"

            return final_response
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
        """
        V4: Search Siêu Rộng (Tên + Mã + Nhóm hàng + Mô tả)
        Kết hợp sức mạnh suy luận của AI và dữ liệu Odoo.
        """
        _logger.info("🔧 AI Smart Search V4 Input: %s", keyword)
        
        if not keyword: return json.dumps({"error": "Thiếu từ khóa"})

        # 1. Clean từ khóa
        stop_words = ["kiểm", "tra", "tồn", "kho", "giá", "xem", "có", "không", "giúp", "em", "mình", "shop"]
        keyword_clean = keyword.lower()
        for w in stop_words: 
            keyword_clean = keyword_clean.replace(f" {w} ", " ").replace(f"{w} ", "")
        keyword_clean = keyword_clean.strip()

        # 2. Tách từ (Tokenize)
        tokens = keyword_clean.split()
        
        # 3. Xây dựng Domain tìm kiếm "Bao vây"
        # Logic: Tìm trong Tên OR Mã OR Barcode OR Mô tả OR Tên Nhóm hàng
        domain = [('active', '=', True)]
        
        for token in tokens:
            token_domain = [
                '|', '|', '|', '|',
                ('name', 'ilike', token),             # Tìm trong Tên
                ('default_code', 'ilike', token),     # Tìm trong Mã nội bộ
                ('barcode', 'ilike', token),          # Tìm trong Mã vạch
                ('description_sale', 'ilike', token), # Tìm trong Mô tả kỹ thuật
                ('categ_id.name', 'ilike', token)     # Tìm trong Tên Nhóm hàng (Category)
            ]
            domain += token_domain

        Product = self.env['product.product'].sudo()
        
        # Lấy 20 kết quả để AI có nhiều lựa chọn lọc
        products = Product.search(domain, limit=20)

        # Fallback: Nếu search gắt (AND) không ra, thử search lỏng (OR) với từ khóa gốc
        if not products and len(tokens) > 1:
            _logger.info("🔧 Fallback search loose...")
            products = Product.search([
                ('active', '=', True), 
                '|', ('name', 'ilike', keyword_clean), ('default_code', 'ilike', keyword_clean)
            ], limit=10)

        if not products:
            # Gợi ý cho AI biết là không tìm thấy để nó báo khách
            return json.dumps({
                "status": "empty", 
                "message": f"Hệ thống không tìm thấy sản phẩm nào khớp với '{keyword_clean}'. Hãy thử từ khóa ngắn hơn hoặc mã model."
            })

        # 4. Xử lý kết quả & Tính điểm ưu tiên (Smart Ranking)
        result_list = []
        for p in products:
            score = 0
            p_name_low = p.name.lower()
            
            # Ưu tiên 1: Có tồn kho
            if p.qty_available > 0: score += 2000
            
            # Ưu tiên 2: Khớp mã chính xác (Code thường ngắn và duy nhất)
            if p.default_code and keyword_clean in p.default_code.lower():
                score += 500
                
            # Ưu tiên 3: Tên sản phẩm bắt đầu bằng từ khóa
            if p_name_low.startswith(keyword_clean): 
                score += 100

            # Ưu tiên 4: Trừ điểm Combo (nếu khách không hỏi combo)
            if "combo" in p_name_low and "combo" not in keyword_clean:
                score -= 50

            result_list.append({
                "name": p.name,
                "code": p.default_code or "",
                "category": p.categ_id.name or "", # Trả về nhóm hàng để AI hiểu ngữ cảnh
                "price": p.list_price,
                "qty": p.qty_available,
                "uom": p.uom_id.name,
                "score": score
            })

        # Sort giảm dần theo điểm
        result_list.sort(key=lambda x: x['score'], reverse=True)
        
        # Cleanup score
        for item in result_list: del item['score']

        return json.dumps(result_list, ensure_ascii=False)

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
        
        local_history = list(messages_history)

        for i in range(3): # Max 3 turns
            try:
                _logger.info("🚀 [%s] Calling Prompt ID: %s", i+1, prompt_id)
                
                response = client.responses.create(
                    model="gpt-4o",
                    prompt={"id": prompt_id},
                    input=local_history,
                )
                
                # --- PARSE RESPONSE ---
                output_msg = None
                tool_calls_found = []
                final_text_found = ""

                # 1. Parse Output (Cấu trúc mới response.output)
                if hasattr(response, 'output'):
                    for item in response.output:
                        item_type = getattr(item, 'type', '')
                        if item_type == 'function_call':
                            tool_calls_found.append(item)
                        elif item_type == 'message':
                            content_list = getattr(item, 'content', [])
                            if content_list and hasattr(content_list[0], 'text'):
                                final_text_found = content_list[0].text
                
                # 2. Fallback (Cấu trúc cũ choices)
                elif hasattr(response, 'choices'):
                    msg = response.choices[0].message
                    if msg.tool_calls:
                        # Convert tool_calls cũ sang format chung nếu cần, hoặc xử lý riêng
                        # Ở đây để đơn giản, ta chỉ log và return lỗi nếu dùng thư viện cũ
                        # Vì log của bạn cho thấy bạn đang dùng thư viện mới (response.output)
                        pass 

                # --- XỬ LÝ LOGIC ---
                if tool_calls_found:
                    # 3. Append AI Message (Giả lập bằng role 'assistant')
                    # Vì API không cho phép gửi 'function_call' object trực tiếp vào input
                    # Ta sẽ gửi một message assistant thông báo đã gọi tool
                    ai_content = "I am calling these tools: " + ", ".join([t.name for t in tool_calls_found])
                    local_history.append({
                        "role": "assistant",
                        "content": ai_content
                    })
                    
                    for tool in tool_calls_found:
                        # Lấy ID và Tên hàm
                        call_id = getattr(tool, 'call_id', None) or getattr(tool, 'id', 'unknown_id')
                        fname = getattr(tool, 'name', 'unknown_func')
                        args_str = getattr(tool, 'arguments', '{}')
                        
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

                        # 4. Append Tool Output (FIX LỖI 400 HERE)
                        # Thay vì role="tool", ta dùng role="user" với prefix rõ ràng để AI hiểu
                        local_history.append({
                            "role": "user",  # <--- ĐỔI TỪ TOOL SANG USER
                            "content": f"Tool '{fname}' (ID: {call_id}) returned result: {tool_res}"
                        })
                    
                    continue # Quay lại vòng lặp để gửi kết quả lên
                
                elif final_text_found:
                    return {"status": "done", "text": final_text_found}
                
                else:
                    return {"status": "error", "text": "AI returned empty response."}

            except Exception as e:
                _logger.exception("OpenAI API Error")
                return {"status": "error", "text": str(e)}
        
        return {"status": "error", "text": "Timeout loop"}

    def _call_openai_api(self, query):
        config = self.env['hlv.chatgpt.config'].get_config()
        if not config or not config.api_key: return "Lỗi: Chưa cấu hình API Key."
        if not config.stock_assistant_id: return "Lỗi: Chưa nhập Assistant ID."

        client = OpenAI(api_key=config.api_key)

        try:
            # GỌI HÀM WORKFLOW MỚI (Thay vì _run_prompt_loop cũ)
            response_text = self._run_assistant_workflow(
                client=client,
                assistant_id=config.stock_assistant_id, # ID asst_5iZ... lấy từ config
                user_query=query
            )
            return response_text

        except Exception as e:
            _logger.exception("OpenAI Workflow Error")
            return f"Lỗi hệ thống: {str(e)}"
class HlvChatgptMessage(models.Model):
    _name = 'hlv.chatgpt.message'
    _description = 'Chi tiết tin nhắn'
    _order = 'create_date asc'

    session_id = fields.Many2one('hlv.chatgpt.session', string='Phiên chat', ondelete='cascade')
    role = fields.Selection([('user', 'Bạn'), ('assistant', 'AI'), ('tool', 'Tool')], string='Role', required=True)
    content = fields.Text(string='Nội dung')