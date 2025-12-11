# models/chatgpt_session.py
import logging
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

    name = fields.Char(string='Chủ đề', default='Cuộc hội thoại mới', required=True)
    user_id = fields.Many2one('res.users', string='Người tạo', default=lambda self: self.env.user)
    last_activity = fields.Datetime(string='Hoạt động cuối', default=fields.Datetime.now)
    
    # Dùng One2many để lưu lịch sử chat
    message_ids = fields.One2many('hlv.chatgpt.message', 'session_id', string='Nội dung hội thoại')
    
    # Ô nhập liệu nhanh (không lưu vào DB lâu dài, chỉ để hứng dữ liệu)
    input_text = fields.Text(string='Nhập tin nhắn...')

    def action_send_message(self):
        """Gửi tin nhắn và nhận phản hồi"""
        self.ensure_one()
        if not self.input_text:
            raise UserError("Vui lòng nhập nội dung tin nhắn.")

        # 1. Tạo tin nhắn của User vào lịch sử
        self.env['hlv.chatgpt.message'].create({
            'session_id': self.id,
            'role': 'user',
            'content': self.input_text
        })
        
        user_query = self.input_text
        self.input_text = "" # Xóa ô nhập sau khi gửi

        # 2. Gọi API OpenAI
        ai_response = self._call_openai_api(user_query)

        # 3. Tạo tin nhắn của AI vào lịch sử
        self.env['hlv.chatgpt.message'].create({
            'session_id': self.id,
            'role': 'assistant',
            'content': ai_response
        })
        
        self.last_activity = fields.Datetime.now()

    def _call_openai_api(self, query):
        """Hàm xử lý gọi API tách biệt"""
        if not OpenAI:
            return "Lỗi: Server chưa cài thư viện openai."
        
        config = self.env['hlv.chatgpt.config'].get_config()
        if not config:
            return "Lỗi: Chưa có cấu hình OpenAI Active."

        client = OpenAI(api_key=config.api_key)

        try:
            # === GỌI API THEO ĐÚNG LOGIC CỦA BẠN ===
            response = client.responses.create(
                model="gpt-4o", 
                prompt={
                    "id": config.prompt_id,
                    "version": config.prompt_version or "3"
                },
                input=[{
                    "role": "user",
                    "content": query
                }],
                text={"format": {"type": "text"}},
                tools=[{
                    "type": "file_search",
                    "vector_store_ids": [config.vector_store_id]
                }],
            )
            
            # Xử lý kết quả trả về
            if hasattr(response, 'output_text'):
                return response.output_text
            elif hasattr(response, 'output'):
                 return response.output
            elif hasattr(response, 'choices') and response.choices:
                return response.choices[0].message.content
            else:
                return str(response)

        except Exception as e:
            _logger.exception("Lỗi OpenAI API")
            return f"Hệ thống gặp lỗi: {str(e)}"


class HlvChatgptMessage(models.Model):
    _name = 'hlv.chatgpt.message'
    _description = 'Chi tiết tin nhắn'
    _order = 'create_date asc' # Tin cũ ở trên, mới ở dưới

    session_id = fields.Many2one('hlv.chatgpt.session', string='Phiên chat', ondelete='cascade')
    role = fields.Selection([('user', 'Bạn'), ('assistant', 'AI')], string='Người gửi', required=True)
    content = fields.Text(string='Nội dung')
    create_date = fields.Datetime(string='Thời gian')