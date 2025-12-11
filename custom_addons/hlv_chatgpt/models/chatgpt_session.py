# models/chatgpt_session.py
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

# Import thư viện OpenAI
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

_logger = logging.getLogger(__name__)

class HlvChatgptSession(models.Model):
    _name = 'hlv.chatgpt.session'
    _description = 'Phiên chat test với ChatGPT'
    _rec_name = 'user_input'
    _order = 'create_date desc'

    user_input = fields.Text(string='Câu hỏi của bạn', required=True)
    response_text = fields.Text(string='ChatGPT trả lời', readonly=True)
    raw_response = fields.Text(string='Raw Response (Debug)', readonly=True, help="Lưu toàn bộ cục JSON trả về để debug")
    state = fields.Selection([
        ('draft', 'Mới'),
        ('done', 'Đã trả lời'),
        ('error', 'Lỗi')
    ], default='draft', string='Trạng thái')

    def action_send_to_chatgpt(self):
        """Hàm gửi tin nhắn sang OpenAI dựa trên Config"""
        self.ensure_one()
        
        # 1. Kiểm tra thư viện
        if not OpenAI:
            raise UserError("Server chưa cài thư viện openai. Vui lòng chạy: pip3 install openai")

        # 2. Lấy cấu hình
        config = self.env['hlv.chatgpt.config'].get_config()
        if not config:
            raise UserError("Chưa có cấu hình OpenAI đang Active.")
        
        # 3. Khởi tạo Client
        client = OpenAI(api_key=config.api_key)

        try:
            _logger.info("Đang gửi request tới OpenAI Prompt ID: %s", config.prompt_id)
            
            # === CODE GỌI API THEO MẪU BẠN GỬI ===
            response = client.responses.create(
                prompt={
                    "id": config.prompt_id,
                    "version": config.prompt_version or "3"
                },
                input=[self.user_input],  # Truyền câu hỏi vào mảng input
                text={
                    "format": {
                        "type": "text"
                    }
                },
                reasoning={},
                tools=[
                    {
                        "type": "file_search",
                        "vector_store_ids": [
                            config.vector_store_id
                        ]
                    }
                ],
                max_output_tokens=2048,
                store=True,
                include=["reasoning.encrypted_content"]
            )
            
            # 4. Xử lý kết quả trả về
            # Lưu ý: Cấu trúc response object của endpoint này có thể khác nhau tùy version
            # Mình sẽ cố gắng lấy text, nếu không được sẽ dump toàn bộ object ra
            
            final_reply = ""
            if hasattr(response, 'output_text'):
                final_reply = response.output_text
            elif hasattr(response, 'choices') and response.choices:
                final_reply = response.choices[0].message.content
            # Kiểm tra nếu trả về dạng khác (vì endpoint responses.create khá mới)
            elif hasattr(response, 'output'):
                 final_reply = response.output
            else:
                final_reply = str(response) # Fallback

            self.write({
                'response_text': final_reply,
                'raw_response': str(response),
                'state': 'done'
            })

        except Exception as e:
            _logger.exception("Lỗi gọi API OpenAI")
            self.write({
                'response_text': f"Lỗi: {str(e)}",
                'state': 'error'
            })