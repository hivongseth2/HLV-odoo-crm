# -*- coding: utf-8 -*-
import logging
import json
import re
import requests
import io
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
except ImportError:
    _logger.warning("Thư viện 'openai' chưa được cài đặt. Hãy chạy: pip install openai")
    OpenAI = None

class HlvChatgptSession(models.Model):
    _name = 'hlv.chatgpt.session'
    _description = 'Phiên Chat AI Product Manager (Single Agent)'
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
    
    message_ids = fields.One2many('hlv.chatgpt.message', 'session_id')
    input_text = fields.Text()

    # =================================================================================
    # 1. CORE LOGIC: GỌI API VÀ XỬ LÝ WORKFLOW
    # =================================================================================
    def _call_openai_api(self, query, image_url=False):
        """Hàm cửa ngõ gọi OpenAI"""
        if not OpenAI: return "Lỗi Server: Chưa cài đặt thư viện OpenAI."
        
        config = self.env['hlv.chatgpt.config'].get_config()
        if not config: return "Lỗi: Chưa có cấu hình ChatGPT."

        # Khởi tạo Client
        client = OpenAI(api_key=config.api_key)
        
        # Lấy ID con Product Manager duy nhất
        assistant_id = config.product_manager_id 
        if not assistant_id:
            return "Lỗi Cấu hình: Chưa nhập ID Assistant (Product Manager)."

        # Chạy Workflow
        return self._run_assistant_workflow(client, assistant_id, query, image_url=image_url)

    def _run_assistant_workflow(self, client, assistant_id, user_query, image_url=False):
        """
        Workflow xử lý chính: 
        1. Quản lý Thread
        2. Gửi tin nhắn (Text/Image)
        3. Chạy Run & Loop (Vòng lặp) để xử lý Tool Call (Hỗ trợ Retry tự động)
        """
        _logger.info("🚀 Start Workflow | Has Image: %s", bool(image_url))

        # A. Quản lý Thread (Tạo mới hoặc lấy cũ)
        thread_id = self.openai_thread_id
        if not thread_id:
            thread = client.beta.threads.create()
            self.openai_thread_id = thread.id
            thread_id = thread.id
        
        # B. Dọn dẹp các Run cũ bị treo (Tránh lỗi 400 Bad Request)
        self._cancel_pending_runs(client, thread_id)

        # C. Chuẩn bị nội dung gửi lên (Payload)
        content_payload = []
        
        # 1. Text
        if user_query:
            content_payload.append({"type": "text", "text": user_query})
        elif image_url:
             # Nếu chỉ gửi ảnh, thêm text mồi để AI biết phải làm gì
             content_payload.append({"type": "text", "text": "Hãy phân tích hình ảnh này và kiểm tra xem sản phẩm đã có mã chưa."})

        # 2. Image (Vision)
        if image_url:
            image_file_id = self._upload_image_to_openai(client, image_url)
            if image_file_id:
                content_payload.append({
                    "type": "image_file",
                    "image_file": {"file_id": image_file_id}
                })
            else:
                content_payload.append({"type": "text", "text": "[System Error: Không tải được ảnh đính kèm]"})

        # D. Gửi Message lên Thread
        if content_payload:
            client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=content_payload
            )

        # E. Tạo Run ban đầu
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id, assistant_id=assistant_id
        )

        # F. VÒNG LẶP XỬ LÝ TOOL (QUAN TRỌNG CHO RETRY)
        # Nếu AI trả về 'requires_action', nghĩa là nó muốn gọi Tool.
        # Ta thực hiện Tool -> Trả kết quả -> AI suy nghĩ tiếp.
        # Nếu AI muốn tìm lại (Retry), nó sẽ lại ra 'requires_action' lần nữa -> Loop tiếp tục chạy.
        while run.status == 'requires_action':
            tool_outputs = []
            
            for tool in run.required_action.submit_tool_outputs.tool_calls:
                fname = tool.function.name
                call_id = tool.id
                args = json.loads(tool.function.arguments or '{}')
                
                _logger.info("⚡ Tool Call: %s | Args: %s", fname, str(args))
                output_str = ""

                # --- XỬ LÝ CÁC FUNCTION ---
                if fname == "search_product_misa":
                    output_str = self._execute_search_misa(args)
                elif fname == "create_product_misa":
                    output_str = self._execute_create_misa(args)
                elif fname == "get_category_info":
                    output_str = self._execute_get_category_info(args)
                else:
                    # File Search được OpenAI tự xử lý, code này chỉ bắt các tool Custom
                    output_str = json.dumps({"error": f"Function {fname} chưa được hỗ trợ trong Code Python"})

                tool_outputs.append({"tool_call_id": call_id, "output": output_str})

            # Submit kết quả Tool lên OpenAI và chờ phản hồi tiếp theo (Poll)
            if tool_outputs:
                run = client.beta.threads.runs.submit_tool_outputs_and_poll(
                    thread_id=thread_id, run_id=run.id, tool_outputs=tool_outputs
                )

        # G. Lấy kết quả cuối cùng (Final Response)
        if run.status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id, limit=1)
            _logger.info("-------------------- DEBUG MESSAGE OPENAI --------------------")
            _logger.info(messages.data)
            _logger.info("--------------------------------------------------------------")
            
            final_response = "..."
            if messages.data:
                # Lấy tin nhắn mới nhất của Assistant
                for msg in messages.data:
                    if msg.role == 'assistant' and msg.content:
                        final_response = msg.content[0].text.value
                        break
            
            # Xóa các ký tự tham chiếu rác (VD: 【4:0†source】)
            final_response = re.sub(r'【.*?】', '', final_response)
            return final_response
        else:
            _logger.error("Run Failed or Expired. Status: %s", run.status)
            return "Hệ thống đang bận hoặc gặp lỗi xử lý. Vui lòng thử lại sau."

    # =================================================================================
    # 2. IMPLEMENTATION (CÁC HÀM CÔNG CỤ)
    # =================================================================================
    
    def _execute_get_category_info(self, args):
        """Tool: Lấy tên nhóm từ ID"""
        _logger.info("ℹ️ Check Category: %s", args)
        cat_id = args.get('category_id')
        if not cat_id: return json.dumps({"error": "Thiếu category_id"})

        try:
            misa_utils = self.env['misa.api.utils'].sudo()
            misa_config = self.env['misa.config'].sudo()
            
            # Lấy Token & Header
            token = misa_utils._fetch_login_crm_token()
            headers = misa_config.get_crm_header(token)
            
            # Gọi hàm tra cứu (đã viết ở Bước 1)
            real_name = misa_utils._get_category_name_by_id(headers, cat_id)

            _logger.info("ℹ️ Check Category: %s", real_name)
            
            return json.dumps({
                "category_id": cat_id,
                "category_name": real_name,
                "note": "Hãy dùng tên này để trả lời User."
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    def _execute_search_misa(self, args):
        """
        Tìm kiếm sản phẩm trong MISA (Live DB)
        AI có thể gọi hàm này nhiều lần (Retry) với các từ khóa khác nhau.
        """
        _logger.info("🔍 MISA Search: %s", args)
        try:
            name = args.get('name')
            code = args.get('code')
            
            # Gọi Utils Model (Đảm bảo bạn đã có model 'misa.api.utils')
            misa_utils = self.env['misa.api.utils'].sudo()
            products = misa_utils.search_product_by_name(name=name, code=code, limit=5)
            
            if not products:
                return json.dumps({
                    "status": "not_found", 
                    "message": "Không tìm thấy trong DB. Hãy thử lại với từ khóa ngắn gọn hơn hoặc tìm theo Mã Model."
                }, ensure_ascii=False)
            
            return json.dumps({
                "status": "found", 
                "count": len(products),
                "data": products,
                "instruction": "Hãy so sánh kỹ Tên và Mã. Nếu trùng khớp -> Báo đã có. Nếu khác -> Đề xuất tạo mới."
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    def _execute_create_misa(self, args):
        """
        Tạo 1 sản phẩm MISA (Single Object)
        Argument nhận vào phẳng: {code, name, price, ...}
        """
        _logger.info("🆕 MISA Create: %s", args)
        try:
            misa_utils = self.env['misa.api.utils'].sudo()
            
            # Gọi hàm tạo raw với tham số từ AI
            misa_id = misa_utils.create_product_misa_raw(
                code=args.get('code'),
                name=args.get('name'),
                price=args.get('price', 0),
                tax_percent=args.get('tax', 10),
                unit_name=args.get('unit', 'Cái'),
                category_name=args.get('category', 'Hàng hóa'),
                product_type=args.get('type', 'goods'), # Hoặc lấy từ args nếu AI gửi
                cat_id=args.get('category_id', False),
                price_pu=args.get('price_pu', 0),
            )
            
            return json.dumps({
                "status": "success", 
                "message": f"Tạo thành công sản phẩm: {args.get('name')}",
                "misa_id": misa_id,
                "code": args.get('code')
            }, ensure_ascii=False)

        except Exception as e:
            _logger.exception("Create Misa Error")
            return json.dumps({"status": "error", "message": f"Lỗi tạo MISA: {str(e)}"}, ensure_ascii=False)

    # =================================================================================
    # 3. HELPER METHODS (Xử lý Ảnh, Run Cleanup)
    # =================================================================================
    def _cancel_pending_runs(self, client, thread_id):
        """Hủy các Run đang treo để tránh lỗi 400"""
        try:
            runs = client.beta.threads.runs.list(thread_id=thread_id, limit=1)
            if runs.data:
                last_run = runs.data[0]
                if last_run.status in ['queued', 'in_progress', 'requires_action']:
                    _logger.warning("⚠️ Cancelling stuck run: %s", last_run.id)
                    client.beta.threads.runs.cancel(thread_id=thread_id, run_id=last_run.id)
        except Exception as e:
            _logger.warning("Check run warning: %s", str(e))

    def _upload_image_to_openai(self, client, image_url):
        """Tải ảnh từ Zalo -> Upload lên OpenAI File Storage"""
        try:
            _logger.info("⬇️ Downloading image: %s", image_url)
            response = requests.get(image_url, timeout=10)
            if response.status_code == 200:
                file_bytes = io.BytesIO(response.content)
                file_bytes.name = "zalo_img.jpg" # Đặt tên giả định
                uploaded_file = client.files.create(file=file_bytes, purpose='vision')
                return uploaded_file.id
            return False
        except Exception as e:
            _logger.error("❌ Image Upload Error: %s", str(e))
            return False

    # =================================================================================
    # 4. ZALO & UI INTEGRATION
    # =================================================================================
    @api.model
    def process_zalo_message(self, zalo_user_id, message_content, zalo_msg_id=False, image_url=False):
        """
        Webhook Entry Point: Nhận tin nhắn từ Zalo -> Xử lý AI -> Trả lời
        """
        # 1. Tìm hoặc tạo Session
        session = self.sudo().search([
            ('zalo_user_id', '=', zalo_user_id)
        ], limit=1, order='last_activity desc')

        if not session:
            session = self.sudo().create({
                'name': f'Zalo Chat - {zalo_user_id}',
                'zalo_user_id': zalo_user_id,
                'state': 'active'
            })

        # 2. Lưu tin nhắn User (Text + Link Ảnh hiển thị)
        display_content = message_content
        if image_url:
            display_content = f"{message_content or '[Gửi ảnh]'} \n[IMG: {image_url}]"

        self.env['hlv.chatgpt.message'].sudo().create({
            'session_id': session.id,
            'role': 'user',
            'content': display_content,
            'zalo_msg_id': zalo_msg_id
        })

        # 3. Gọi AI
        ai_reply = session._call_openai_api(message_content, image_url=image_url)

        # 4. Lưu câu trả lời AI
        self.env['hlv.chatgpt.message'].sudo().create({
            'session_id': session.id,
            'role': 'assistant',
            'content': ai_reply
        })
        session.sudo().write({'last_activity': fields.Datetime.now()})

        return ai_reply

    def action_send_message(self):
        """Nút gửi tin nhắn từ giao diện Odoo"""
        self.ensure_one()
        if not self.input_text: raise UserError("Chưa nhập nội dung.")
        
        # Lưu User Msg
        self.env['hlv.chatgpt.message'].create({
            'session_id': self.id, 
            'role': 'user', 
            'content': self.input_text
        })
        
        # Gọi AI
        response = self._call_openai_api(self.input_text)
        
        # Lưu AI Msg
        self.env['hlv.chatgpt.message'].create({
            'session_id': self.id, 
            'role': 'assistant', 
            'content': response
        })
        self.input_text = ""

class HlvChatgptMessage(models.Model):
    _name = 'hlv.chatgpt.message'
    _description = 'Lịch sử tin nhắn Chat'
    _order = 'create_date asc'

    session_id = fields.Many2one('hlv.chatgpt.session', ondelete='cascade')
    role = fields.Selection([('user','User'),('assistant','AI'),('system','System')], required=True)
    content = fields.Text(string="Nội dung")
    zalo_msg_id = fields.Char(string="Msg ID Zalo (Deduplication)")