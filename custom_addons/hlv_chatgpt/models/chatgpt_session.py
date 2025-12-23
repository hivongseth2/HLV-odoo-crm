# -*- coding: utf-8 -*-
import logging
import json
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import io
_logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
except ImportError:
    _logger.warning("Thư viện 'openai' chưa cài đặt.")
    OpenAI = None

class HlvChatgptSession(models.Model):
    _name = 'hlv.chatgpt.session'
    _description = 'Phiên Chat AI Product Manager'
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
    
    # Đã xóa field current_agent_key vì chỉ còn 1 con
    message_ids = fields.One2many('hlv.chatgpt.message', 'session_id')
    input_text = fields.Text()

    # =================================================================================
    # 1. CORE PROCESS (XỬ LÝ CHÍNH)
    # =================================================================================
    def _call_openai_api(self, query, image_url=False):
        if not OpenAI: return "Lỗi server: Thiếu thư viện OpenAI."
        
        config = self.env['hlv.chatgpt.config'].get_config()
        if not config: return "Lỗi: Chưa có cấu hình."

        client = OpenAI(api_key=config.api_key)
        
        # Luôn gọi con Product Manager
        assistant_id = config.product_manager_id
        if not assistant_id:
            return "Lỗi: Chưa cấu hình Product Manager ID."

        return self._run_assistant_workflow(client, assistant_id, query, image_url=image_url)

    def _run_assistant_workflow(self, client, assistant_id, user_query, image_url=False):
        """
        Workflow đơn giản hóa: Gửi tin -> Chạy Run -> Xử lý Tool (Misa) -> Trả về kết quả
        """
        _logger.info("🚀 Workflow Start | Has Image: %s", bool(image_url))

        # A. Quản lý Thread
        thread_id = self.openai_thread_id
        if not thread_id:
            thread = client.beta.threads.create()
            self.openai_thread_id = thread.id
            thread_id = thread.id
        
        # B. Hủy Run cũ bị treo (Clean up)
        try:
            runs = client.beta.threads.runs.list(thread_id=thread_id, limit=1)
            if runs.data:
                last_run = runs.data[0]
                if last_run.status in ['queued', 'in_progress', 'requires_action', 'cancelling']:
                    if last_run.status != 'cancelling':
                        client.beta.threads.runs.cancel(thread_id=thread_id, run_id=last_run.id)
        except Exception as e:
            _logger.warning("⚠️ Warning check run: %s", str(e))

        # C. Chuẩn bị Payload (Text + Image)
        content_payload = []
        
        # 1. Xử lý Text
        if user_query:
            content_payload.append({"type": "text", "text": user_query})
        elif image_url:
             # Nếu chỉ có ảnh mà không có text, thêm text mồi
             content_payload.append({"type": "text", "text": "Hãy phân tích hình ảnh này và kiểm tra xem sản phẩm đã có mã chưa."})

        # 2. Xử lý Image (Vision)
        if image_url:
            try:
                _logger.info("⬇️ Downloading image: %s", image_url)
                response = requests.get(image_url, timeout=10)
                if response.status_code == 200:
                    file_bytes = io.BytesIO(response.content)
                    file_bytes.name = "zalo_img.jpg"
                    uploaded_file = client.files.create(file=file_bytes, purpose='vision')
                    content_payload.append({
                        "type": "image_file",
                        "image_file": {"file_id": uploaded_file.id}
                    })
                else:
                    content_payload.append({"type": "text", "text": "[System Error: Không tải được ảnh]"})
            except Exception as e:
                 _logger.error("❌ Image Error: %s", str(e))
                 content_payload.append({"type": "text", "text": "[System Error: Lỗi xử lý ảnh]"})

        # D. Gửi Message lên Thread
        if content_payload:
            client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=content_payload
            )

        # E. Chạy Run
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id, assistant_id=assistant_id
        )

        # F. Xử lý Tool Call (Chỉ còn MISA Tools)
        if run.status == 'requires_action':
            tool_outputs = []
            
            for tool in run.required_action.submit_tool_outputs.tool_calls:
                fname = tool.function.name
                call_id = tool.id
                args = json.loads(tool.function.arguments or '{}')
                
                _logger.info("⚡ Tool Call: %s | Args: %s", fname, str(args))
                output_str = ""

                # --- NHÓM TOOL MISA ---
                if fname == "search_product_misa":
                    output_str = self._execute_search_misa(args)
                elif fname == "create_product_misa":
                    output_str = self._execute_create_misa(args)
                elif fname == "handoff_to_router":
                    # Mặc dù user nói bỏ router, nhưng Prompt vẫn có lệnh này để handle Lạc Đề.
                    # Ta trả về thông báo để AI lịch sự từ chối.
                    output_str = "System: Chức năng chuyển hướng (Routing) đã bị tắt. Hãy thông báo cho người dùng rằng bạn chỉ hỗ trợ 'Tra cứu' và 'Tạo sản phẩm'."
                else:
                    # Với file_search, OpenAI tự xử lý, code này thường không bắt được trừ khi function definition sai.
                    output_str = json.dumps({"error": f"Function {fname} not supported in Python code"})

                tool_outputs.append({"tool_call_id": call_id, "output": output_str})

            # Submit output và đợi kết quả cuối cùng
            if tool_outputs:
                run = client.beta.threads.runs.submit_tool_outputs_and_poll(
                    thread_id=thread_id, run_id=run.id, tool_outputs=tool_outputs
                )

        # G. Lấy kết quả cuối cùng
        messages = client.beta.threads.messages.list(thread_id=thread_id, limit=1)
        final_response = "..."
        if messages.data:
            # Lấy tin nhắn mới nhất của Assistant
            for msg in messages.data:
                 if msg.role == 'assistant' and msg.content:
                    final_response = msg.content[0].text.value
                    break
        
        # Clean text rác
        final_response = re.sub(r'【.*?】', '', final_response)
        return final_response
    
    # =================================================================================
    # 2. IMPLEMENTATION (CÁC HÀM THỰC THI)
    # =================================================================================
    
    def _execute_search_misa(self, args):
        """Tìm kiếm sản phẩm trong MISA/Odoo"""
        _logger.info("🔍 MISA Search: %s", args)
        try:
            name = args.get('name')
            code = args.get('code') # AI có thể trích xuất mã từ ảnh hoặc text
            
            misa_utils = self.env['misa.api.utils'].sudo()
            # Giả định hàm search_product_by_name của bạn hỗ trợ tìm gần đúng
            products = misa_utils.search_product_by_name(name=name, code=code, limit=5)
            
            if not products:
                return json.dumps({
                    "status": "not_found", 
                    "message": "Không tìm thấy trong Live DB."
                }, ensure_ascii=False)
            
            return json.dumps({
                "status": "found", 
                "count": len(products),
                "data": products, # Trả về list để AI so sánh
                "instruction": "Hãy kiểm tra kỹ tên và mã. Nếu trùng khớp, hãy báo đã có. Nếu khác biệt, đề xuất tạo mới."
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    def _execute_create_misa(self, args):
        """Tạo sản phẩm MISA"""
        _logger.info("🆕 MISA Create: %s", args)
        try:
            misa_utils = self.env['misa.api.utils'].sudo()
            
            misa_id = misa_utils.create_product_misa_raw(
                code=args.get('code'),
                name=args.get('name'),
                price=args.get('price', 0),
                tax_percent=args.get('tax', 8), # Thuế mặc định 8 hoặc 10 tùy cấu hình
                unit_name=args.get('unit', 'Cái'),
                category_name=args.get('category', 'Hàng hóa'),
                product_type=args.get('type', 'goods'),
                cat_id = args.get('category_id', False),
            )
            
            return json.dumps({
                "status": "success", 
                "message": f"Đã tạo thành công. ID: {misa_id}",
                "data": {"code": args.get('code'), "name": args.get('name')}
            }, ensure_ascii=False)

        except Exception as e:
            _logger.exception("Create Misa Error")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    # --- ZALO PROCESS ---
    @api.model
    def process_zalo_message(self, zalo_user_id, message_content, zalo_msg_id=False, image_url=False):
        """Hàm nhận Webhook từ Zalo"""
        session = self.sudo().search([
            ('zalo_user_id', '=', zalo_user_id)
        ], limit=1, order='last_activity desc')

        if not session:
            session = self.sudo().create({
                'name': f'Zalo Chat - {zalo_user_id}',
                'zalo_user_id': zalo_user_id,
                'state': 'active'
            })

        # 1. Lưu User Message
        display_content = message_content
        if image_url:
            display_content = f"{message_content or 'Gửi ảnh'} \n[IMG: {image_url}]"

        self.env['hlv.chatgpt.message'].sudo().create({
            'session_id': session.id,
            'role': 'user',
            'content': display_content,
            'zalo_msg_id': zalo_msg_id
        })

        # 2. Gọi AI (Single Agent)
        ai_reply = session._call_openai_api(message_content, image_url=image_url)

        # 3. Lưu Assistant Message
        self.env['hlv.chatgpt.message'].sudo().create({
            'session_id': session.id,
            'role': 'assistant',
            'content': ai_reply
        })
        session.sudo().write({'last_activity': fields.Datetime.now()})

        return ai_reply

    # --- ACTION BUTTON TRÊN VIEW FORM ---
    def action_send_message(self):
        self.ensure_one()
        if not self.input_text: raise UserError("Chưa nhập nội dung")
        
        self.env['hlv.chatgpt.message'].create({'session_id': self.id, 'role': 'user', 'content': self.input_text})
        response = self._call_openai_api(self.input_text)
        self.env['hlv.chatgpt.message'].create({'session_id': self.id, 'role': 'assistant', 'content': response})
        self.input_text = ""

# Giữ nguyên Class Message
class HlvChatgptMessage(models.Model):
    _name = 'hlv.chatgpt.message'
    _description = 'Tin nhắn'
    _order = 'create_date asc'
    session_id = fields.Many2one('hlv.chatgpt.session', ondelete='cascade')
    role = fields.Selection([('user','User'),('assistant','AI'),('system','System')], required=True)
    content = fields.Text()
    zalo_msg_id = fields.Char()