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
    
    # --- ZALO INTERGRATION ---
    zalo_user_id = fields.Char(string="Zalo User ID", index=True, help="ID người dùng từ Zalo OA")
    # -------------------------

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
        stop_words = [
            "kiểm", "tra", "tồn", "kho", "giá", "xem", "có", "không", "giúp", "em", "mình", "shop", "ad", "admin",
            "check", "bao", "nhiêu", "tiền", "cái", "con", "cây", "chiếc"
        ]
        keyword_clean = keyword.lower()
        for w in stop_words: keyword_clean = keyword_clean.replace(f" {w} ", " ").replace(f"{w} ", "")
        keyword_clean = keyword_clean.strip() or keyword

        # Search
        tokens = keyword_clean.split()
        domain = [('active', '=', True)]
        for token in tokens:
            domain += ['|', '|', '|', ('name', 'ilike', token), ('default_code', 'ilike', token), ('barcode', 'ilike', token), ('description_sale', 'ilike', token)]
        
        products = self.env['product.product'].sudo().search(domain, limit=50)
        
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
    # 2. XỬ LÝ GỬI NHẬN (ACTION BUTTON & ZALO PROCESS)
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
        self.state = 'active'

        # Gọi AI
        ai_reply = self._call_openai_api(user_query)

        # Lưu tin nhắn AI
        self.env['hlv.chatgpt.message'].create({
            'session_id': self.id, 'role': 'assistant', 'content': ai_reply
        })
        self.last_activity = fields.Datetime.now()

    def process_zalo_message(self, zalo_user_id, message_content, zalo_msg_id=False):
        """
        Hàm này được gọi từ Webhook Zalo.
        Logic: Tìm session cũ hoặc tạo mới -> Hỏi AI -> Trả về câu trả lời
        """
        # A. Tìm phiên chat gần nhất của User này (hoặc tạo mới)
        session = self.search([
            ('zalo_user_id', '=', zalo_user_id)
        ], limit=1, order='last_activity desc')

        if not session:
            session = self.create({
                'name': f'Zalo Chat - {zalo_user_id}',
                'zalo_user_id': zalo_user_id,
                'state': 'active'
            })

        # B. Lưu tin nhắn của User vào lịch sử
        self.env['hlv.chatgpt.message'].create({
            'session_id': session.id,
            'role': 'user',
            'content': message_content,
            'zalo_msg_id': zalo_msg_id
        })

        # C. Gọi API OpenAI (Sử dụng lại hàm _call_openai_api đã viết)
        # Lưu ý: Cần gọi trong ngữ cảnh của session tìm được
        ai_response_text = session._call_openai_api(message_content)

        # D. Lưu câu trả lời của AI vào lịch sử
        self.env['hlv.chatgpt.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': ai_response_text
        })

        # E. Cập nhật thời gian hoạt động
        session.write({'last_activity': fields.Datetime.now()})

        return ai_response_text

    # =================================================================================
    # 3. CORE LOGIC: CHẠY PROMPT LOOP
    # =================================================================================
    def _run_prompt_loop(self, client, prompt_id, messages_history):
        """Vòng lặp an toàn: Hỗ trợ cả Dict và Object để tránh lỗi AttributeError"""
        local_history = list(messages_history)
        _logger.info("🏁 Loop Start | Prompt ID: %s", prompt_id)

        # --- Helper Function: Lấy dữ liệu an toàn bất chấp Dict hay Object ---
        def get_val(obj, key, default=None):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)
        # -------------------------------------------------------------------

        for i in range(3): # Max 3 turns
            try:
                # 1. GỌI API
                response = client.chat.completions.create(
                    model="gpt-4o",
                    prompt={"id": prompt_id},
                    input=local_history,
                )
                
                # 2. PARSE RESPONSE (Dùng hàm get_val để tránh lỗi)
                tool_calls_found = []
                final_text_found = ""
                
                # Lấy output list an toàn
                output_items = get_val(response, 'output')
                choices = get_val(response, 'choices')

                if output_items: # Cấu trúc mới/Wrapper
                    for item in output_items:
                        itype = get_val(item, 'type')
                        if itype == 'function_call': 
                            tool_calls_found.append(item)
                        elif itype == 'message': 
                            content_list = get_val(item, 'content', [])
                            if content_list:
                                final_text_found = get_val(content_list[0], 'text')
                
                elif choices: # Cấu trúc chuẩn OpenAI
                    choice = choices[0]
                    msg = get_val(choice, 'message')
                    t_calls = get_val(msg, 'tool_calls')
                    if t_calls: tool_calls_found = t_calls
                    
                    content = get_val(msg, 'content')
                    if content: final_text_found = content

                # --- XỬ LÝ TOOL CALL ---
                if tool_calls_found:
                    # 1. Log AI Message (Fix lỗi tại đây)
                    tool_names = []
                    for t in tool_calls_found:
                        # Thử lấy trong 'function' trước
                        func = get_val(t, 'function')
                        if func:
                            name = get_val(func, 'name')
                        else:
                            name = get_val(t, 'name') # Fallback
                        tool_names.append(str(name))

                    ai_msg = "I am calling tools: " + ", ".join(tool_names)
                    local_history.append({"role": "assistant", "content": ai_msg})
                    
                    handoff_target = None
                    
                    # 2. Thực thi từng tool
                    for tool in tool_calls_found:
                        # Lấy function name và args an toàn
                        func = get_val(tool, 'function')
                        if func:
                            fname = get_val(func, 'name')
                            args_str = get_val(func, 'arguments')
                        else:
                            fname = get_val(tool, 'name')
                            args_str = get_val(tool, 'arguments')
                        
                        call_id = get_val(tool, 'id') or get_val(tool, 'call_id') or 'unknown_id'
                        
                        # Parse Arguments
                        try:
                            if isinstance(args_str, dict): 
                                args = args_str
                            else: 
                                args = json.loads(args_str or '{}')
                        except:
                            args = {}

                        _logger.info("⚡ Tool: %s | Args: %s", fname, args)

                        # Check Handoff
                        if fname == "handoff_to_stock_agent": handoff_target = "stock"
                        elif fname == "handoff_to_naming_agent": handoff_target = "naming"
                        
                        # Execute Search
                        tool_res = "Done"
                        if fname == "search_product_stock":
                            tool_res = self._execute_search_product_stock(args.get('keyword'))
                        elif fname == "check_product_existence":
                            tool_res = self._execute_check_product_existence(args.get('keyword'))
                        
                        # 3. Append kết quả vào history
                        local_history.append({
                            "role": "user", 
                            "content": f"Tool '{fname}' (ID: {call_id}) Result: {tool_res}"
                        })

                    # 4. Handoff nếu cần
                    if handoff_target:
                        return {"status": "handoff", "target": handoff_target}

                    # 5. Continue vòng lặp
                    continue 
                
                # --- TRẢ LỜI TEXT ---
                elif final_text_found:
                    return {"status": "done", "text": final_text_found}
            
            except Exception as e:
                _logger.exception("GPT Loop Error")
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
        
        # 2. Determine Prompt ID
        target_id = config.router_prompt_id
        # if self.current_agent == 'stock': target_id = config.stock_prompt_id
        # elif self.current_agent == 'naming': target_id = config.naming_prompt_id

        # 3. CHẠY VÒNG 1 (Với Prompt hiện tại)
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
    
    # --- ZALO INTERGRATION ---
    zalo_msg_id = fields.Char('Zalo Message ID', index=True, help="ID tin nhắn từ Zalo để tránh trùng lặp")
    # -------------------------