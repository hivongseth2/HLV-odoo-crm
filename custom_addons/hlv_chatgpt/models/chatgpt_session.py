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
    _logger.warning("Thư viện 'openai' chưa được cài đặt. Vui lòng chạy: pip install openai")
    OpenAI = None

class HlvChatgptSession(models.Model):
    _name = 'hlv.chatgpt.session'
    _description = 'Phiên Chat AI (Assistant Workflow)'
    _rec_name = 'name'
    _order = 'last_activity desc'

    # --- FIELDS ---
    name = fields.Char(string='Chủ đề', default='Hội thoại mới', required=True)
    user_id = fields.Many2one('res.users', string='Người tạo', default=lambda self: self.env.user)
    last_activity = fields.Datetime(string='Hoạt động cuối', default=fields.Datetime.now)
    
    # Lưu ID luồng chat của OpenAI để nhớ ngữ cảnh
    openai_thread_id = fields.Char(string="OpenAI Thread ID", readonly=True)
    
    state = fields.Selection([
        ('new', 'Mới'),
        ('active', 'Đang hoạt động'),
        ('archived', 'Lưu trữ')
    ], default='new', string='Trạng thái')

    message_ids = fields.One2many('hlv.chatgpt.message', 'session_id', string='Nội dung hội thoại')
    input_text = fields.Text(string='Nhập tin nhắn...')

    # =================================================================================
    # 1. CORE ENGINE: CHẠY ASSISTANT WORKFLOW (LOGIC MỚI)
    # =================================================================================
    def _run_assistant_workflow(self, client, assistant_id, user_query):
        """
        Chạy Workflow tự động: Gửi tin nhắn -> Chờ AI suy nghĩ -> AI gọi Tool -> Trả lời
        """
        _logger.info("🚀 Starting Workflow | Assistant: %s", assistant_id)

        # A. QUẢN LÝ THREAD (LUỒNG CHAT)
        thread_id = self.openai_thread_id
        if not thread_id:
            try:
                thread = client.beta.threads.create()
                self.openai_thread_id = thread.id
                thread_id = thread.id
                _logger.info("✨ Created New Thread: %s", thread_id)
            except Exception as e:
                return f"Lỗi tạo luồng chat: {str(e)}"
        else:
            _logger.info("🔄 Resuming Thread: %s", thread_id)

        # B. GỬI TIN NHẮN USER
        try:
            client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=user_query
            )
        except Exception as e:
            return f"Lỗi gửi tin nhắn: {str(e)}"

        # C. KÍCH HOẠT RUN (AI BẮT ĐẦU NGHĨ)
        try:
            run = client.beta.threads.runs.create_and_poll(
                thread_id=thread_id,
                assistant_id=assistant_id,
            )
        except Exception as e:
            return f"Lỗi khởi chạy Assistant: {str(e)}"

        # D. XỬ LÝ VÒNG LẶP TOOL CALL
        final_response = "Hệ thống không phản hồi."

        # Nếu AI yêu cầu gọi Tool (Trạng thái: requires_action)
        if run.status == 'requires_action':
            tool_outputs = []
            
            # Duyệt qua danh sách các tool AI muốn gọi
            for tool in run.required_action.submit_tool_outputs.tool_calls:
                fname = tool.function.name
                args_str = tool.function.arguments
                call_id = tool.id
                
                try: args = json.loads(args_str)
                except: args = {}
                
                _logger.info("⚡ Workflow calling Tool: %s | Args: %s", fname, args)

                # --- ROUTER GỌI HÀM PYTHON ODOO ---
                output_str = json.dumps({"error": "Unknown function"})
                
                if fname == "search_product_stock":
                    # Gọi hàm Search V9 (đã tối ưu bên dưới)
                    output_str = self._execute_search_product_stock(args.get('keyword'))
                
                elif fname == "check_product_existence":
                    output_str = self._execute_check_product_existence(args.get('keyword'))

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
                    return f"Lỗi khi gửi kết quả tool lên OpenAI: {str(e)}"

        # E. LẤY KẾT QUẢ CUỐI CÙNG
        if run.status == 'completed': 
            messages = client.beta.threads.messages.list(thread_id=thread_id, limit=1)
            if messages.data:
                for content in messages.data[0].content:
                    if hasattr(content, 'text'):
                        final_response = content.text.value
                        # Xóa các chú thích nguồn [source] nếu có
                        final_response = re.sub(r'【.*?】', '', final_response)
        else:
            final_response = f"Workflow kết thúc bất thường. Trạng thái: {run.status}"

        return final_response

    # =================================================================================
    # 2. HÀM KẾT NỐI API (CÓ BỘ LỌC ID)
    # =================================================================================
    def _call_openai_api(self, query):
        if not OpenAI: return "Lỗi: Server chưa cài thư viện 'openai'."
        
        config = self.env['hlv.chatgpt.config'].get_config()
        if not config or not config.api_key: return "Lỗi: Chưa cấu hình API Key."
        if not config.stock_assistant_id: return "Lỗi: Chưa nhập Stock Assistant ID."

        # --- FIX LỖI ID: TỰ ĐỘNG LÀM SẠCH ---
        # Cắt bỏ mọi thứ sau dấu '&' hoặc '?' nếu user copy nhầm link
        raw_id = config.stock_assistant_id.strip()
        clean_assistant_id = raw_id.split('&')[0].split('?')[0].strip()
        
        # Validate cơ bản
        if not clean_assistant_id.startswith("asst_"):
            return f"Lỗi ID: Assistant ID phải bắt đầu bằng 'asst_'. (Hiện tại: {clean_assistant_id})"

        client = OpenAI(api_key=config.api_key)

        try:
            # Gọi hàm Workflow mới
            response_text = self._run_assistant_workflow(
                client=client,
                assistant_id=clean_assistant_id,
                user_query=query
            )
            return response_text

        except Exception as e:
            _logger.exception("OpenAI Connection Error")
            return f"Lỗi kết nối: {str(e)}"

    # =================================================================================
    # 3. TOOLS LOGIC (HÀM TÌM KIẾM SẢN PHẨM V9)
    # =================================================================================
    def _execute_search_product_stock(self, keyword):
        """
        V9: Search Thông Minh - Ưu tiên khớp Tên & Lọc rác (Anti-Noise)
        """
        _logger.info("🔧 AI Search V9 Input: %s", keyword)
        if not keyword: return json.dumps({"error": "Thiếu từ khóa"})

        Product = self.env['product.product'].sudo()
        
        # 1. CLEANING
        stop_words = ["kiểm", "tra", "tồn", "kho", "giá", "xem", "có", "không", "bao", "nhiêu", "cái", "con", "máy", "bộ"]
        keyword_clean = keyword.lower()
        for w in stop_words: 
            keyword_clean = keyword_clean.replace(f" {w} ", " ").replace(f"{w} ", "")
        keyword_clean = keyword_clean.strip()
        if not keyword_clean: keyword_clean = keyword
        
        tokens = keyword_clean.split()

        # 2. BROAD SEARCH (Tìm rộng)
        domain = [('active', '=', True)]
        
        # Build Domain OR (Name | Code | Barcode)
        if tokens:
            # Logic: (Name contains T1) OR (Code contains T1) ...
            # Cách viết domain gọn cho Odoo
            search_domain = []
            for token in tokens:
                 search_domain += ['|', '|', ('name', 'ilike', token), ('default_code', 'ilike', token), ('barcode', 'ilike', token)]
            
            # Cân bằng toán tử OR (Polish Notation): Cần (N-1) dấu '|' ở đầu
            # Nhưng ở trên ta đã nhét '|' vào giữa rồi.
            # Cách an toàn nhất là dùng phép cộng domain chuẩn:
            final_domain = []
            for token in tokens:
                sub_domain = ['|', '|', ('name', 'ilike', token), ('default_code', 'ilike', token), ('barcode', 'ilike', token)]
                if not final_domain:
                    final_domain = sub_domain
                else:
                    final_domain = ['|'] + final_domain + sub_domain
            domain += final_domain

        products = Product.search(domain, limit=30)
        
        if not products:
             return json.dumps({"status": "empty", "message": f"Không tìm thấy sản phẩm nào khớp '{keyword_clean}'."})

        # 3. SCORING (Chấm điểm)
        result_list = []
        junk_keywords = ["vỏ", "pin", "sạc", "thùng", "combo", "phụ tùng", "tem", "nhãn"]
        
        for p in products:
            score = 0
            p_name = p.name.lower()
            p_code = (p.default_code or "").lower()
            
            # Tiêu chí: Khớp token
            matched = sum(1 for t in tokens if t in p_name or t in p_code)
            score += matched * 1000

            # Tiêu chí: Khớp chuỗi liền mạch
            if keyword_clean in p_name: score += 2000
            if keyword_clean in p_code: score += 3000

            # Tiêu chí: Có tồn kho
            if p.qty_available > 0: score += 1000

            # Tiêu chí: Trừ điểm rác (Nếu khách không tìm rác)
            for junk in junk_keywords:
                if junk in p_name and junk not in keyword_clean:
                    score -= 5000 # Đẩy xuống đáy

            result_list.append({
                "name": p.name,
                "code": p.default_code or "N/A",
                "price": p.list_price,
                "qty": p.qty_available,
                "uom": p.uom_id.name,
                "_score": score
            })

        # 4. SORT & RETURN
        result_list.sort(key=lambda x: x['_score'], reverse=True)
        final_results = result_list[:5]
        for item in final_results: del item['_score']

        return json.dumps(final_results, ensure_ascii=False)

    def _execute_check_product_existence(self, keyword):
        # Hàm phụ trợ đơn giản
        return self._execute_search_product_stock(keyword)

    # =================================================================================
    # 4. UI ACTIONS
    # =================================================================================
    def action_send_message(self):
        self.ensure_one()
        if not self.input_text: raise UserError("Vui lòng nhập nội dung.")

        # 1. Lưu User Message
        self.env['hlv.chatgpt.message'].create({
            'session_id': self.id, 'role': 'user', 'content': self.input_text
        })
        
        user_query = self.input_text
        self.input_text = ""

        # 2. Gọi AI
        ai_reply = self._call_openai_api(user_query)

        # 3. Lưu AI Message
        self.env['hlv.chatgpt.message'].create({
            'session_id': self.id, 'role': 'assistant', 'content': ai_reply
        })
        self.last_activity = fields.Datetime.now()

class HlvChatgptMessage(models.Model):
    _name = 'hlv.chatgpt.message'
    _description = 'Chi tiết tin nhắn'
    _order = 'create_date asc'

    session_id = fields.Many2one('hlv.chatgpt.session', string='Phiên chat', ondelete='cascade')
    role = fields.Selection([('user', 'Bạn'), ('assistant', 'AI')], string='Role', required=True)
    content = fields.Text(string='Nội dung')