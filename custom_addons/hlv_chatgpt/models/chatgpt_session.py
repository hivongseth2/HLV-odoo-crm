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
        V8: Search Phân Tầng (Tiered Search)
        Mục tiêu: Đảm bảo tìm ra đúng Mã Hàng kể cả khi nó bị chìm giữa 1000 phụ kiện.
        """
        _logger.info("🔧 AI Smart Search V8 Input: %s", keyword)
        
        if not keyword: return json.dumps({"error": "Thiếu từ khóa"})

        Product = self.env['product.product'].sudo()
        collected_ids = [] # Danh sách ID đã tìm thấy để tránh trùng
        final_products = self.env['product.product']

        # Xử lý từ khóa
        keyword_clean = keyword.strip()
        
        # --- TẦNG 1: QUÉT MÃ CHÍNH XÁC (QUAN TRỌNG NHẤT) ---
        # Nếu AI gửi đúng mã (tìm được từ file), tầng này sẽ bắt dính ngay lập tức.
        # Tìm chính xác 100% hoặc chứa mã
        domain_tier1 = [
            ('active', '=', True),
            '|', 
            ('default_code', '=ilike', keyword_clean), # Khớp mã tuyệt đối (không phân biệt hoa thường)
            ('default_code', 'ilike', keyword_clean)   # Mã chứa từ khóa
        ]
        products_tier1 = Product.search(domain_tier1, limit=10)
        
        for p in products_tier1:
            if p.id not in collected_ids:
                final_products += p
                collected_ids.append(p.id)

        # --- TẦNG 2: TÌM THEO TÊN (START WITH) ---
        # Ưu tiên những sp có tên bắt đầu bằng từ khóa
        if len(collected_ids) < 20: # Chỉ tìm tiếp nếu chưa đủ hàng
            domain_tier2 = [
                ('active', '=', True),
                ('id', 'not in', collected_ids), # Loại trừ những thằng đã tìm thấy ở trên
                ('name', 'ilike', keyword_clean + '%') # Bắt đầu bằng từ khóa
            ]
            products_tier2 = Product.search(domain_tier2, limit=10)
            
            for p in products_tier2:
                final_products += p
                collected_ids.append(p.id)

        # --- TẦNG 3: TÌM RỘNG (TOKENIZE) - LOGIC CŨ ---
        # Chỉ chạy khi 2 tầng trên chưa tìm đủ hàng
        if len(collected_ids) < 40:
            limit_remain = 40 - len(collected_ids)
            
            # Xử lý stop words cho tầng này
            stop_words = ["kiểm", "tra", "tồn", "kho", "giá", "xem", "có", "không", "shop", "ad", "ơi", "chiếc", "cái"]
            kw_token = keyword.lower()
            for w in stop_words: kw_token = kw_token.replace(f" {w} ", " ").replace(f"{w} ", "")
            tokens = kw_token.split()

            if tokens:
                domain_tier3 = [('active', '=', True), ('id', 'not in', collected_ids)]
                for token in tokens:
                    domain_tier3 += [
                        '|', '|', '|', '|',
                        ('name', 'ilike', token),
                        ('default_code', 'ilike', token),
                        ('barcode', 'ilike', token),
                        ('categ_id.name', 'ilike', token),
                        ('description_sale', 'ilike', token)
                    ]
                
                products_tier3 = Product.search(domain_tier3, limit=limit_remain)
                final_products += products_tier3

        if not final_products:
            return json.dumps({"status": "empty", "message": f"Không tìm thấy sản phẩm '{keyword}'."})

        # --- CHẤM ĐIỂM & SẮP XẾP (PYTHON) ---
        # Lúc này final_products đã chứa: [Mã Chính xác] + [Tên Bắt đầu] + [Tìm rộng]
        # Chúng ta sort lại một lần nữa cho chắc chắn.
        
        result_list = []
        for p in final_products:
            score = 0
            p_name = p.name.lower()
            p_code = (p.default_code or "").lower()
            kw_low = keyword_clean.lower()

            # 1. Điểm Tuyệt đối cho Mã
            if p_code == kw_low: score += 10000
            elif kw_low in p_code: score += 5000
            
            # 2. Điểm Tồn kho
            if p.qty_available > 0: score += 2000
            
            # 3. Điểm Tên
            if p_name.startswith(kw_low): score += 1000
            if kw_low in p_name: score += 500

            # 4. Trừ điểm rác (Phụ kiện)
            junk_words = ["vỏ", "tem", "nhãn", "hộp", "thùng", "ốc", "vít", "phụ tùng", "chổi than"]
            # Nếu khách không tìm đích danh từ rác thì mới trừ
            if not any(j in kw_low for j in junk_words):
                for junk in junk_words:
                    if junk in p_name:
                        score -= 3000 # Đẩy xuống đáy xã hội
                        break

            result_list.append({
                "name": p.name,
                "code": p.default_code or "N/A",
                "price": p.list_price,
                "qty": p.qty_available,
                "uom": p.uom_id.name,
                "score": score
            })

        # Sort
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