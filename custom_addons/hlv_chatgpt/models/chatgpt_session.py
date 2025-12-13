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
        local_history = list(messages_history)
        _logger.info("🏁 Loop Start | Prompt ID: %s", prompt_id)

        for i in range(3):
            try:
                response = client.responses.create(
                    model="gpt-4o",
                    prompt={"id": prompt_id},
                    input=local_history,
                )
                
                # Parse
                tool_calls_found = []
                final_text_found = ""
                
                if hasattr(response, 'output'):
                    for item in response.output:
                        if item.type == 'function_call': tool_calls_found.append(item)
                        elif item.type == 'message': final_text_found = item.content[0].text

                if tool_calls_found:
                    # 1. Báo cho history biết AI đang gọi tool
                    ai_msg = "Tool Call: " + ", ".join([t.name for t in tool_calls_found])
                    local_history.append({"role": "assistant", "content": ai_msg})
                    
                    handoff_target = None
                    
                    # 2. Chạy từng tool
                    for tool in tool_calls_found:
                        fname = tool.name
                        args = json.loads(tool.arguments)
                        call_id = getattr(tool, 'call_id', 'id')
                        
                        _logger.info("⚡ Tool: %s", fname)

                        # --- ƯU TIÊN ROUTER ---
                        if fname == "handoff_to_stock_agent":
                            handoff_target = "stock"
                            # Không break vội, cứ để nó chạy hết các tool khác (nếu có) hoặc xử lý logic append
                        elif fname == "handoff_to_naming_agent":
                            handoff_target = "naming"
                        
                        # --- XỬ LÝ TOOL ---
                        tool_res = "Done"
                        if fname == "search_product_stock":
                            tool_res = self._execute_search_product_stock(args.get('keyword'))
                        elif fname == "check_product_existence":
                            tool_res = self._execute_check_product_existence(args.get('keyword'))
                        # ... các tool khác ...

                        # 3. Append kết quả tool vào history (QUAN TRỌNG)
                        local_history.append({
                            "role": "user", 
                            "content": f"Tool '{fname}' (ID: {call_id}) Result: {tool_res}"
                        })

                    # 4. Nếu có lệnh chuyển hướng thì return NGAY sau khi xử lý xong các tool
                    if handoff_target:
                        return {"status": "handoff", "target": handoff_target}

                    # Nếu không chuyển hướng -> Lặp lại để AI đọc kết quả tool
                    continue
                
                elif final_text_found:
                    return {"status": "done", "text": final_text_found}
            
            except Exception as e:
                _logger.exception("GPT Error")
                return {"status": "error", "text": str(e)}
        
        return {"status": "error", "text": "Timeout"}
    
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