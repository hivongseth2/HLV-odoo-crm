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
    
    zalo_user_id = fields.Char(string="Zalo User ID", index=True, help="ID người dùng từ Zalo OA")
    name = fields.Char(string='Chủ đề', default='Cuộc hội thoại mới', required=True)
    user_id = fields.Many2one('res.users', string='Người tạo', default=lambda self: self.env.user)
    last_activity = fields.Datetime(string='Hoạt động cuối', default=fields.Datetime.now)
    
    # === THÊM FIELD STATE ĐỂ FIX LỖI ===
    state = fields.Selection([
        ('new', 'Mới'),
        ('active', 'Đang hoạt động'),
        ('archived', 'Lưu trữ')
    ], default='new', string='Trạng thái')
    # ===================================

    # Dùng One2many để lưu lịch sử chat
    message_ids = fields.One2many('hlv.chatgpt.message', 'session_id', string='Nội dung hội thoại')
    
    # Ô nhập liệu nhanh
    input_text = fields.Text(string='Nhập tin nhắn...')

    def action_send_message(self):
        """Gửi tin nhắn và nhận phản hồi"""
        self.ensure_one()
        if not self.input_text:
            raise UserError("Vui lòng nhập nội dung tin nhắn.")

        # 1. Tạo tin nhắn của User
        self.env['hlv.chatgpt.message'].create({
            'session_id': self.id,
            'role': 'user',
            'content': self.input_text
        })
        
        user_query = self.input_text
        self.input_text = "" 
        self.state = 'active' # Cập nhật trạng thái

        # 2. Gọi API OpenAI
        ai_response = self._call_openai_api(user_query)

        # 3. Tạo tin nhắn của AI
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
            # === GỌI API ===
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
        
        
    def process_zalo_message(self, zalo_user_id, message_content):
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
            'content': message_content
        })

        # C. Gọi API OpenAI (Sử dụng lại hàm _call_openai_api đã viết)
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


class HlvChatgptMessage(models.Model):
    _name = 'hlv.chatgpt.message'
    _description = 'Chi tiết tin nhắn'
    _order = 'create_date asc'

    session_id = fields.Many2one('hlv.chatgpt.session', string='Phiên chat', ondelete='cascade')
    role = fields.Selection([('user', 'Bạn'), ('assistant', 'AI')], string='Người gửi', required=True)
    content = fields.Text(string='Nội dung')
    create_date = fields.Datetime(string='Thời gian')