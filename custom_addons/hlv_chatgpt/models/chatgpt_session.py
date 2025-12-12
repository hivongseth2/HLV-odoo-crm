# models/chatgpt_session.py
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json 
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
    
    
    def _get_tools_schema(self):
        """
        Khai báo danh sách các hành động mà AI có thể làm.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_product_stock",
                    "description": "Tra cứu thông tin sản phẩm, giá bán và số lượng tồn kho trong hệ thống.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string", 
                                "description": "Tên sản phẩm hoặc mã sản phẩm người dùng muốn tìm. Ví dụ: 'máy khoan', '6203'..."
                            }
                        },
                        "required": ["keyword"]
                    }
                }
            }
        ]

    # -------------------------------------------------------------------------
    # 2. HÀM THỰC THI LOGIC TRONG ODOO (ACTION)
    # -------------------------------------------------------------------------
    def _execute_tool_search_product(self, keyword):
        """
        Trả về dữ liệu JSON thô để AI tự quyết định cách hiển thị.
        """
        _logger.info("🤖 AI tra cứu (Smart Search JSON): %s", keyword)
        
        if not keyword:
            return json.dumps({"error": "Thiếu từ khóa tìm kiếm"})

        keyword = keyword.strip()
        tokens = keyword.split()
        
        # 1. Search rộng (lấy cả Combo, phụ kiện...)
        domain = [('active', '=', True)]
        for token in tokens:
            token_domain = [
                '|', '|', '|',
                ('name', 'ilike', token),
                ('default_code', 'ilike', token),
                ('barcode', 'ilike', token),
                ('description_sale', 'ilike', token)
            ]
            domain += token_domain

        Product = self.env['product.product'].sudo()
        # Lấy nhiều kết quả hơn (ví dụ 15) để AI có đủ dữ liệu lọc
        products = Product.search(domain, limit=15)

        if not products and len(tokens) > 1:
             # Fallback search lỏng
            domain_loose = [('active', '=', True), ('name', 'ilike', keyword)] 
            products = Product.search(domain_loose, limit=10)

        if not products:
            return json.dumps({"status": "empty", "message": f"Không tìm thấy sản phẩm '{keyword}'"})

        # 2. Xử lý dữ liệu trả về
        result_list = []
        for p in products:
            # Tính điểm ưu tiên (Score) để sort
            # Nếu tên sản phẩm BẮT ĐẦU bằng từ khóa -> Điểm cao (Ưu tiên máy lẻ)
            # Nếu tên sản phẩm chứa "Combo" -> Điểm thấp hơn (trừ khi khách tìm combo)
            score = 0
            p_name_lower = p.name.lower()
            keyword_lower = keyword.lower()

            if p_name_lower.startswith(keyword_lower):
                score += 10
            if "combo" in p_name_lower:
                score -= 5 # Hạ ưu tiên Combo xuống một chút
            
            result_list.append({
                "name": p.name,
                "code": p.default_code or "N/A",
                "price": p.list_price,
                "qty": p.qty_available,
                "uom": p.uom_id.name,
                "score": score # Trường ảo để sort
            })

        # 3. Sắp xếp lại danh sách: Điểm cao lên đầu
        result_list.sort(key=lambda x: x['score'], reverse=True)

        # Xóa trường score trước khi gửi cho AI cho gọn
        for item in result_list:
            del item['score']

        # Trả về JSON String
        return json.dumps(result_list, ensure_ascii=False)

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
        if not OpenAI: return "Lỗi: Server chưa cài thư viện openai."
        config = self.env['hlv.chatgpt.config'].get_config()
        if not config: return "Lỗi: Chưa có cấu hình OpenAI Active."

        client = OpenAI(api_key=config.api_key)
        
        # === SYSTEM PROMPT "KHÔN NGOAN" HƠN ===
        system_instruction = """
        Bạn là trợ lý bán hàng chuyên nghiệp của Hoàng Long Vũ (HLV).
        Nhiệm vụ: Tra cứu tồn kho và báo giá.
        
        QUY TẮC XỬ LÝ DỮ LIỆU TÌM KIẾM (QUAN TRỌNG):
        1. Hệ thống sẽ trả về danh sách sản phẩm dạng JSON bao gồm cả Máy lẻ và Combo.
        2. Nếu khách hàng CHỈ hỏi tên máy (ví dụ: "M18 FPD3"):
           - Ưu tiên số 1: Hiển thị Máy thân (Body/Bare) hoặc Máy bộ (Kit) chính xác.
           - ẨN bớt các gói Combo phức tạp (trừ khi máy lẻ hết hàng thì mới gợi ý Combo).
           - Không liệt kê quá 3-5 sản phẩm chính, tránh spam.
        3. Nếu khách hàng hỏi "Combo":
           - Lúc này mới hiển thị danh sách các Combo.
        4. Trình bày ngắn gọn: "Tên hàng (Mã) - Tồn: X - Giá: Y".
        5. Luôn format giá tiền có dấu phân cách (ví dụ: 1.200.000 đ).
        """

        messages = [{"role": "system", "content": system_instruction}]
        # Lấy 5 tin nhắn gần nhất để làm context (tiết kiệm token)
        recent_msgs = self.env['hlv.chatgpt.message'].search([
            ('session_id', '=', self.id)
        ], order='create_date desc', limit=5)
        
        for msg in reversed(recent_msgs):
            # Lưu ý: OpenAI yêu cầu role chuẩn (user/assistant)
            # Vì model message của mình lưu role 'assistant' rồi nên dùng được luôn
            messages.append({"role": msg.role, "content": msg.content or ""})

        # Thêm câu hỏi hiện tại của user
        messages.append({"role": "user", "content": query})

        try:
            # === BƯỚC 1: Gửi Request lần đầu (Kèm Tools) ===
            completion = client.chat.completions.create(
                model="gpt-4o", # Nên dùng gpt-4o hoặc gpt-3.5-turbo-0125 để hỗ trợ tool tốt
                messages=messages,
                tools=self._get_tools_schema(),
                tool_choice="auto" # Để AI tự quyết định có dùng tool hay không
            )
            
            response_message = completion.choices[0].message
            tool_calls = response_message.tool_calls

            # === BƯỚC 2: Kiểm tra xem AI có muốn dùng Tool không? ===
            if tool_calls:
                _logger.info("🤖 AI quyết định gọi Tool: %s", tool_calls)
                
                # Thêm tin nhắn của AI (chứa tool_calls) vào lịch sử hội thoại tạm
                messages.append(response_message)

                # Duyệt qua các tool mà AI muốn gọi (có thể gọi nhiều tool 1 lúc)
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    
                    tool_output = "Lỗi: Không tìm thấy chức năng này."
                    
                    # Mapping tên hàm -> Logic Odoo
                    if function_name == "search_product_stock":
                        tool_output = self._execute_tool_search_product(function_args.get("keyword"))
                    
                    # Thêm kết quả từ Odoo vào lịch sử hội thoại tạm để AI đọc
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": tool_output,
                    })

                # === BƯỚC 3: Gửi lại toàn bộ kết quả cho AI để nó viết câu trả lời cuối cùng ===
                second_response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages
                )
                return second_response.choices[0].message.content

            else:
                # Nếu AI không dùng tool, trả về text bình thường
                return response_message.content

        except Exception as e:
            _logger.exception("Lỗi OpenAI API Tool Call")
            return f"Hệ thống gặp lỗi khi xử lý: {str(e)}"
        
        
    def process_zalo_message(self, zalo_user_id, message_content,zalo_msg_id=False):
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
    zalo_msg_id = fields.Char('Zalo Message ID', index=True, help="ID tin nhắn từ Zalo để tránh trùng lặp")