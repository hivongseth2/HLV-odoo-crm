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
        """
        V9: Chiến lược Ưu Tiên Tên (Name-First Strategy)
        Phù hợp khi AI gửi xuống Tên đầy đủ từ file Vector.
        """
        _logger.info("🔧 AI Smart Search V9 Input: %s", keyword)
        if not keyword: return json.dumps({"error": "Thiếu từ khóa"})

        Product = self.env['product.product'].sudo()
        keyword_clean = keyword.strip()
        
        # 1. Tách từ khóa
        stop_words = ["kiểm", "tra", "tồn", "kho", "giá", "xem", "có", "không", "shop", "ad", "ơi", "chiếc", "cái", "là", "của"]
        kw_token = keyword.lower()
        for w in stop_words: kw_token = kw_token.replace(f" {w} ", " ").replace(f"{w} ", "")
        tokens = kw_token.split()

        # 2. Search SQL (Tìm rộng)
        # Nếu keyword dài, ta chỉ cần tìm sp chứa ít nhất 1-2 từ quan trọng là được, sau đó Python lọc lại
        domain = [('active', '=', True)]
        
        if len(tokens) > 0:
            # Lấy các từ có độ dài > 2 ký tự để search cho chính xác
            valid_tokens = [t for t in tokens if len(t) > 2]
            if not valid_tokens: valid_tokens = tokens
            
            # Tìm những sp chứa ít nhất 1 trong các từ này
            sub_domain = ['|'] * (len(valid_tokens) - 1)
            for token in valid_tokens:
                sub_domain += [
                    '|', '|',
                    ('name', 'ilike', token),
                    ('default_code', 'ilike', token),
                    ('product_variant_ids.default_code', 'ilike', token)
                ]
            domain += sub_domain

        # Lấy rộng 50 kết quả
        products = Product.search(domain, limit=50)

        if not products:
            return json.dumps({"status": "empty", "message": f"Không tìm thấy sản phẩm '{keyword}'."})

        # 3. CHẤM ĐIỂM & SẮP XẾP (PYTHON RANKING)
        result_list = []
        kw_low = keyword_clean.lower()

        for p in products:
            score = 0
            p_name = p.name.lower()
            p_code = (p.default_code or "").lower()
            
            # --- TIÊU CHÍ 1: KHỚP TÊN (QUAN TRỌNG NHẤT) ---
            # Đếm số từ trong keyword xuất hiện trong tên sản phẩm
            matches = sum(1 for t in tokens if t in p_name)
            
            # Tỷ lệ khớp (VD: Keyword 5 từ, Tên chứa 4 từ -> 80%)
            match_ratio = matches / len(tokens) if tokens else 0
            
            score += match_ratio * 5000 # Điểm rất cao cho việc khớp tên
            
            # Nếu tên khớp y chang hoặc chứa trọn vẹn keyword
            if kw_low in p_name: 
                score += 3000

            # --- TIÊU CHÍ 2: KHỚP MÃ ---
            if kw_low in p_code: score += 2000
            
            # --- TIÊU CHÍ 3: TỒN KHO ---
            if p.qty_available > 0: score += 1000

            # --- TIÊU CHÍ 4: TRỪ ĐIỂM RÁC ---
            junk_words = ["vỏ", "tem", "nhãn", "hộp", "thùng", "ốc", "vít", "phụ tùng"]
            # Nếu trong keyword KHÔNG CÓ từ rác mà tên sp LẠI CÓ -> Trừ điểm
            found_junk_in_keyword = any(j in kw_low for j in junk_words)
            if not found_junk_in_keyword:
                for junk in junk_words:
                    if junk in p_name:
                        score -= 2000
                        break
            
            # Trừ điểm Combo nếu không tìm combo
            if "combo" in p_name and "combo" not in kw_low:
                score -= 1000

            result_list.append({
                "name": p.name,
                "code": p.default_code or "N/A",
                "price": p.list_price,
                "qty": p.qty_available,
                "uom": p.uom_id.name,
                "score": score
            })

        # Sort giảm dần theo điểm
        result_list.sort(key=lambda x: x['score'], reverse=True)
        
        # Lấy Top 10
        final_results = result_list[:10]
        for item in final_results: del item['score']

        return json.dumps(final_results, ensure_ascii=False)

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
                        pass 

                # --- XỬ LÝ LOGIC ---
                if tool_calls_found:
                    # 3. Append AI Message (Giả lập bằng role 'assistant')
                    ai_content = "I am calling these tools: " + ", ".join([t.name for t in tool_calls_found])
                    local_history.append({
                        "role": "assistant",
                        "content": ai_content
                    })
                    
                    for tool in tool_calls_found:
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
        if self.current_agent == 'stock': target_id = config.stock_prompt_id
        elif self.current_agent == 'naming': target_id = config.naming_prompt_id

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