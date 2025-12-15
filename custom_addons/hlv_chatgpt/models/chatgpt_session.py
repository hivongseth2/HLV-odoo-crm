# -*- coding: utf-8 -*-
import logging
import json
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
except ImportError:
    _logger.warning("Thư viện 'openai' chưa cài đặt.")
    OpenAI = None

class HlvChatgptSession(models.Model):
    _name = 'hlv.chatgpt.session'
    _description = 'Phiên Chat AI Multi-Agent'
    _rec_name = 'name'
    _order = 'last_activity desc'
    
    # --- FIELDS ---
    name = fields.Char(string='Chủ đề', default='Hội thoại mới', required=True)
    state = fields.Selection([('new', 'Mới'), ('active', 'Đang hoạt động')], default='new')
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user)
    last_activity = fields.Datetime(default=fields.Datetime.now)
    zalo_user_id = fields.Char(string="Zalo User ID", index=True)

    # --- OPENAI STATE ---
    openai_thread_id = fields.Char(string="Thread ID", readonly=True)
    
    # Lưu trạng thái đang chat với con nào
    current_agent_key = fields.Selection([
        ('router', 'Router'),
        ('stock', 'Stock'),
        ('naming', 'Naming')
    ], default='router', string="Đang chat với")

    message_ids = fields.One2many('hlv.chatgpt.message', 'session_id')
    input_text = fields.Text()

    # =================================================================================
    # 1. ORCHESTRATOR (NGƯỜI ĐIỀU PHỐI)
    # =================================================================================
    def _call_openai_api(self, query):
        if not OpenAI: return "Lỗi server: Thiếu thư viện OpenAI."
        
        config = self.env['hlv.chatgpt.config'].get_config()
        if not config: return "Lỗi: Chưa có cấu hình."

        client = OpenAI(api_key=config.api_key)
        
        # 1. Xác định Assistant ID dựa trên trạng thái hiện tại
        target_assistant_id = self._get_assistant_id_by_key(config, self.current_agent_key)
        
        if not target_assistant_id:
            return f"Lỗi: Không tìm thấy ID cho agent '{self.current_agent_key}'"

        # 2. Chạy Workflow
        return self._run_assistant_workflow(client, target_assistant_id, query, config)

    def _get_assistant_id_by_key(self, config, key):
        """Hàm phụ trợ lấy ID từ config"""
        if key == 'stock': return config.stock_id
        if key == 'naming': return config.naming_id
        return config.router_id # Mặc định là router

    # =================================================================================
    # 2. CORE WORKFLOW (XỬ LÝ CHUYỂN MÁY)
    # =================================================================================
    def _run_assistant_workflow(self, client, assistant_id, user_query, config):
        _logger.info("🚀 Workflow Start | Agent: %s (%s)", self.current_agent_key, assistant_id)

        # A. Xử lý ID (Clean ID)
        clean_id = assistant_id.split('&')[0].strip()

        # B. Quản lý Thread
        thread_id = self.openai_thread_id
        if not thread_id:
            thread = client.beta.threads.create()
            self.openai_thread_id = thread.id
            thread_id = thread.id
        
        # C. Gửi tin nhắn User
        client.beta.threads.messages.create(
            thread_id=thread_id, role="user", content=user_query
        )

        # D. Chạy Run
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id, assistant_id=clean_id
        )

        # E. Xử lý Tool Call (QUAN TRỌNG: HANDOFF VS FUNCTION)
        final_response = "..."
        
        if run.status == 'requires_action':
            tool_outputs = []
            is_handoff = False
            next_agent_key = 'router'

            for tool in run.required_action.submit_tool_outputs.tool_calls:
                fname = tool.function.name
                call_id = tool.id
                args = json.loads(tool.function.arguments or '{}')
                
                _logger.info("⚡ Tool Call: %s", fname)

                # --- LOGIC CHUYỂN MÁY (HANDOFF) ---
                if fname == "handoff_to_stock":
                    is_handoff = True
                    next_agent_key = 'stock'
                    output_str = "Handoff initiated." 
                
                elif fname == "handoff_to_naming":
                    is_handoff = True
                    next_agent_key = 'naming'
                    output_str = "Handoff initiated."
                    
                elif fname == "handoff_to_router":
                    is_handoff = True
                    next_agent_key = 'router' # Quay về Router
                    output_str = "Quay về Tổng đài."

                # --- LOGIC NGHIỆP VỤ (STOCK) ---
                elif fname == "search_product_stock":
                    output_str = self._execute_search_product_stock(args.get('keyword'))
                else:
                    output_str = json.dumps({"error": "Unknown function"})

                tool_outputs.append({"tool_call_id": call_id, "output": output_str})

            # Submit output lên OpenAI
            if tool_outputs:
                client.beta.threads.runs.submit_tool_outputs_and_poll(
                    thread_id=thread_id, run_id=run.id, tool_outputs=tool_outputs
                )

            # --- NẾU LÀ HANDOFF: GỌI ĐỆ QUY SANG CON KHÁC NGAY ---
            if is_handoff:
                _logger.info("🔀 Switching Agent: %s -> %s", self.current_agent_key, next_agent_key)
                
                # 1. Cập nhật trạng thái phiên chat
                self.current_agent_key = next_agent_key
                
                # 2. Lấy ID con mới
                new_assistant_id = self._get_assistant_id_by_key(config, next_agent_key)
                
                # 3. Kỹ thuật: Inject Context (Nhét câu hỏi vào mồm User để con mới biết làm gì)
                return self._run_assistant_workflow(client, new_assistant_id, user_query, config)

        # F. Lấy kết quả cuối cùng (Nếu không phải handoff)
        messages = client.beta.threads.messages.list(thread_id=thread_id, limit=1)
        if messages.data and messages.data[0].content:
            final_response = messages.data[0].content[0].text.value
            final_response = re.sub(r'【.*?】', '', final_response)
            
        return final_response

    # =================================================================================
    # 3. STOCK LOGIC (Hàm Search V9)
    # =================================================================================
    def _execute_search_product_stock(self, keyword):
        """V9: Search Thông Minh - Ưu tiên khớp Tên & Lọc rác"""
        _logger.info("🔧 AI Search V9 Input: %s", keyword)
        if not keyword: return json.dumps({"error": "Thiếu từ khóa"})

        Product = self.env['product.product'].sudo()
        
        # 1. CLEANING
        stop_words = ["kiểm", "tra", "tồn", "kho", "giá", "xem", "có", "không", "bao", "nhiêu", "cái", "con", "máy", "bộ"]
        keyword_clean = keyword.lower()
        for w in stop_words: 
            keyword_clean = keyword_clean.replace(f" {w} ", " ").replace(f"{w} ", "")
        keyword_clean = keyword_clean.strip() or keyword
        
        tokens = keyword_clean.split()

        # 2. BROAD SEARCH
        domain = [('active', '=', True)]
        if tokens:
            final_domain = []
            for token in tokens:
                sub_domain = ['|', '|', ('name', 'ilike', token), ('default_code', 'ilike', token), ('barcode', 'ilike', token)]
                if not final_domain: final_domain = sub_domain
                else: final_domain = ['|'] + final_domain + sub_domain
            domain += final_domain

        products = Product.search(domain, limit=300)
        
        if not products:
             return json.dumps({"status": "empty", "message": f"Không tìm thấy sản phẩm nào khớp '{keyword_clean}'."})

        # 3. SCORING
        result_list = []
        junk_keywords = ["vỏ", "pin", "sạc", "thùng", "combo", "phụ tùng", "tem", "nhãn"]
        
        for p in products:
            score = 0
            p_name = p.name.lower()
            p_code = (p.default_code or "").lower()
            
            matched = sum(1 for t in tokens if t in p_name or t in p_code)
            score += matched * 1000
            if keyword_clean in p_name: score += 2000
            if keyword_clean in p_code: score += 3000
            if p.qty_available > 0: score += 1000

            for junk in junk_keywords:
                if junk in p_name and junk not in keyword_clean:
                    score -= 5000 

            result_list.append({
                "name": p.name, "code": p.default_code, "price": p.list_price,
                "qty": p.qty_available, "uom": p.uom_id.name, "_score": score
            })

        result_list.sort(key=lambda x: x['_score'], reverse=True)
        final_results = result_list[:40]
        for item in final_results: del item['_score']

        return json.dumps(final_results, ensure_ascii=False)

    # =================================================================================
    # 4. ZALO INTEGRATION & UI ACTIONS (Hàm bạn bị thiếu nằm ở đây)
    # =================================================================================
    @api.model
    def process_zalo_message(self, zalo_user_id, message_content, zalo_msg_id=False):
        """
        Hàm này được Zalo Webhook gọi. 
        Nó tự tìm session cũ để tiếp tục chat hoặc tạo mới.
        """
        # A. Tìm session
        session = self.sudo().search([
            ('zalo_user_id', '=', zalo_user_id)
        ], limit=1, order='last_activity desc')

        if not session:
            session = self.sudo().create({
                'name': f'Zalo Chat - {zalo_user_id}',
                'zalo_user_id': zalo_user_id,
                'state': 'active'
            })

        # B. Lưu User Msg
        self.env['hlv.chatgpt.message'].sudo().create({
            'session_id': session.id,
            'role': 'user',
            'content': message_content,
            'zalo_msg_id': zalo_msg_id
        })

        # C. Gọi AI (Dùng logic Multi-Agent đã viết ở trên)
        ai_reply = session._call_openai_api(message_content)

        # D. Lưu AI Msg
        self.env['hlv.chatgpt.message'].sudo().create({
            'session_id': session.id,
            'role': 'assistant',
            'content': ai_reply
        })
        session.sudo().write({'last_activity': fields.Datetime.now()})

        return ai_reply

    def action_send_message(self):
        self.ensure_one()
        if not self.input_text: raise UserError("Chưa nhập nội dung")
        
        self.env['hlv.chatgpt.message'].create({'session_id': self.id, 'role': 'user', 'content': self.input_text})
        response = self._call_openai_api(self.input_text)
        self.env['hlv.chatgpt.message'].create({'session_id': self.id, 'role': 'assistant', 'content': response})
        self.input_text = ""

    def action_reset_router(self):
        self.current_agent_key = 'router'
        self.env['hlv.chatgpt.message'].create({
            'session_id': self.id, 'role': 'system', 'content': 'Đã chuyển về Tổng đài.'
        })

class HlvChatgptMessage(models.Model):
    _name = 'hlv.chatgpt.message'
    _description = 'Tin nhắn'
    _order = 'create_date asc'
    session_id = fields.Many2one('hlv.chatgpt.session', ondelete='cascade')
    role = fields.Selection([('user','User'),('assistant','AI'),('system','System')], required=True)
    content = fields.Text()
    zalo_msg_id = fields.Char()