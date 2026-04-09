# -*- coding: utf-8 -*-
import logging
import json
import re
import requests
import io
import base64
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
except ImportError:
    _logger.warning("Thư viện 'openai' chưa được cài đặt. Hãy chạy: pip install openai")
    OpenAI = None

# --- CONSTANTS ---
VECTOR_STORE_IDS = ["vs_69328ab5789081918759b56def1c641a"]

# Built-in (non-MISA) tool schemas — MISA tools loaded dynamically from misa.crm.tools
BUILTIN_TOOLS = [
    {
      "type": "file_search",
      "vector_store_ids": VECTOR_STORE_IDS
    },
    {
      "type": "web_search",
      "filters": None,
      "search_context_size": "medium",
      "user_location": {
        "type": "approximate",
        "city": None,
        "country": None,
        "region": None,
        "timezone": None
      }
    },
]

class HlvChatgptSession(models.Model):
    _name = 'hlv.chatgpt.session'
    _description = 'Phiên Chat AI Product Manager (Responses API)'
    _rec_name = 'name'
    _order = 'last_activity desc'
    
    # --- FIELDS ---
    name = fields.Char(string='Chủ đề', default='Hội thoại mới', required=True)
    state = fields.Selection([('new', 'Mới'), ('active', 'Đang hoạt động')], default='new')
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user)
    last_activity = fields.Datetime(default=fields.Datetime.now)
    zalo_user_id = fields.Char(string="Zalo User ID", index=True)

    # --- ROUTING / ASSIGNMENT ---
    ai_care = fields.Boolean(
        string='Ngân Hà chăm sóc',
        default=False,
        help='Nếu bật, hội thoại này sẽ được AI (Ngân Hà) trả lời tự động khi có tin nhắn Zalo OA đến.'
    )
    tag_ids = fields.Many2many(
        'hlv.chatgpt.tag',
        'hlv_chatgpt_session_tag_rel',
        'session_id',
        'tag_id',
        string='Tags'
    )

    # --- CUSTOMER SUMMARY / MEMORY (editable by humans) ---
    customer_summary = fields.Text(
        string='Tóm tắt khách hàng',
        help='Tóm tắt ngắn: khách là ai, đang hỏi gì, nhu cầu chính. Có thể chỉnh sửa thủ công.'
    )
    customer_need = fields.Text(
        string='Nhu cầu / yêu cầu',
        help='Ghi rõ nhu cầu, tiêu chí, ràng buộc (giá, tiến độ, model, số lượng...). Có thể chỉnh sửa.'
    )
    advice_log = fields.Text(
        string='Con đã tư vấn gì',
        help='Log tóm tắt các lời tư vấn/đề xuất đã đưa ra. Có thể chỉnh sửa.'
    )
    memory_notes = fields.Text(
        string='Memory (ghi chú nội bộ)',
        help='Ghi chú lâu dài để AI dùng làm ngữ cảnh. Người dùng có thể xem và chỉnh sửa.'
    )
    tone_instructions = fields.Text(
        string='Thái độ / giọng điệu của con',
        default='Xưng con, gọi papa. Trả lời gọn, rõ, lịch sự. Ưu tiên hỏi lại để chốt nhu cầu trước khi báo giá.',
        help='Chỉ dẫn thái độ/giọng điệu. Ví dụ: "ngắn gọn", "thân mật", "kỹ thuật", "bán hàng mềm"...'
    )

    last_customer_message = fields.Text(string='Tin nhắn khách gần nhất', readonly=True)
    last_ai_reply = fields.Text(string='Phản hồi AI gần nhất', readonly=True)

    # --- OPENAI STATE (Giữ lại để tránh lỗi migration, nhưng không dùng nữa) ---
    openai_thread_id = fields.Char(string="Legacy Thread ID", readonly=True)
    
    message_ids = fields.One2many('hlv.chatgpt.message', 'session_id')
    input_text = fields.Text()

    # =================================================================================
    # 1. CORE LOGIC: GỌI API RESPONSES.CREATE
    # =================================================================================
    def _call_openai_api(self, query, image_url=False):
        """Hàm cửa ngõ gọi OpenAI Responses API"""
        if not OpenAI: return "Lỗi Server: Chưa cài đặt thư viện OpenAI."
        
        config = self.env['hlv.chatgpt.config'].get_config()
        if not config: return "Lỗi: Chưa có cấu hình ChatGPT."

        prompt_id = config.prompt_id
        if not prompt_id: return "Lỗi: Chưa cấu hình Prompt ID."

        # Khởi tạo Client
        client = OpenAI(api_key=config.api_key)
        
        # Chạy Workflow
        return self._run_gpt_prompt_workflow(client, query, prompt_id, image_url=image_url)

    # =================================================================================
    # 1.5. SUMMARY / MEMORY UPDATE (OPTIONAL)
    # =================================================================================
    def _update_session_summary(self, user_query, ai_reply):
        """Cập nhật nhanh summary/need/advice_log dựa trên lượt chat mới.

        Mục tiêu: giúp người dùng nhìn được "memory" ngay trong Odoo và chỉnh sửa được.
        Ưu tiên: an toàn + đơn giản. Nếu lỗi thì bỏ qua, không làm fail luồng trả lời.
        """
        self.ensure_one()

        try:
            # Chỉ update khi có AI trả lời
            if not ai_reply:
                return

            # Giới hạn độ dài để tránh phình field
            def _cap(txt, n=2000):
                txt = (txt or '').strip()
                return txt[:n]

            vals = {}

            # Customer summary: seed 1 lần nếu đang trống
            if not (self.customer_summary or '').strip():
                seed = (user_query or '').strip()
                if seed:
                    vals['customer_summary'] = _cap(seed, 500)

            # Customer needs: append bullet-ish (keep compact)
            need_line = (user_query or '').strip()
            if need_line:
                existing = (self.customer_need or '').strip()
                new_block = (existing + "\n" if existing else "") + f"- {need_line}"
                vals['customer_need'] = _cap(new_block, 2000)

            # Advice log: append the AI reply
            reply_line = (ai_reply or '').strip()
            if reply_line:
                existing = (self.advice_log or '').strip()
                new_block = (existing + "\n\n" if existing else "") + f"AI: {reply_line}"
                vals['advice_log'] = _cap(new_block, 4000)

            if vals:
                # Write once to avoid multiple implicit writes inside a background cursor
                self.sudo().write(vals)

        except Exception as e:
            _logger.warning("Summary update skipped due to error: %s", e)

    def _get_tools_schema(self):
        """Merge MISA CRM tool schemas (from registry) with built-in tools."""
        misa_schemas = self.env['misa.crm.tools'].sudo().get_all_schemas()
        return misa_schemas + BUILTIN_TOOLS

    def _run_gpt_prompt_workflow(self, client, user_query, prompt_id, image_url=False):
        """
        Workflow xử lý chính với client.responses.create:
        1. Xây dựng lịch sử hội thoại (Input Messages)
        2. Gọi API với Prompt đã lưu (Stored Prompt)
        3. Xử lý Tool Calls (Loop)
        """
        _logger.info("🚀 Start Prompt Workflow | Has Image: %s", bool(image_url))

        # A. Xây dựng danh sách tin nhắn đầu vào (Session Memory + Conversation History + New Message)
        input_messages = []

        # Inject editable memory + tone as a system message (high priority)
        mem_parts = []
        if self.tone_instructions:
            mem_parts.append(f"TONE / STYLE:\n{self.tone_instructions}")
        if self.customer_summary:
            mem_parts.append(f"CUSTOMER SUMMARY:\n{self.customer_summary}")
        if self.customer_need:
            mem_parts.append(f"CUSTOMER NEEDS:\n{self.customer_need}")
        if self.advice_log:
            mem_parts.append(f"WHAT WE ALREADY ADVISED:\n{self.advice_log}")
        if self.memory_notes:
            mem_parts.append(f"MEMORY NOTES (editable by humans):\n{self.memory_notes}")

        if mem_parts:
            input_messages.append({
                "role": "system",
                "content": "\n\n".join(mem_parts)
            })

        # Append recent chat history
        input_messages.extend(self._get_conversation_history())
        
        # Thêm tin nhắn mới nhất của User
        current_content = []
        if user_query:
            current_content.append({"type": "input_text", "text": user_query})
        
        if image_url:
             # Nếu chỉ gửi ảnh, thêm text mồi
             if not user_query:
                 current_content.append({"type": "input_text", "text": "Hãy phân tích hình ảnh này."})
             
             image_data = self._download_image_to_base64(image_url)
             if image_data:
                current_content.append({
                    "type": "input_image",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}
                })
             else:
                current_content.append({"type": "text", "text": "[System Error: Không tải được ảnh đính kèm]"})

        if current_content:
            input_messages.append({
                "role": "user",
                "content": current_content
            })

        # B. VÒNG LẶP XỬ LÝ (CALL -> TOOL -> CALL)
        # API Responses không dùng ThreadRun stateful như Assistant/Threads API cũ.
        # Ta cần tự quản lý loop tool calls.
        
        MAX_STEPS = 5 # Tránh loop vô tận
        step_count = 0
        final_response_text = "..."

        while step_count < MAX_STEPS:
            step_count += 1
            try:
                # Gọi API
                # Gọi API
                response = client.responses.create(
                    prompt={
                        "id": prompt_id,
                    },
                    input=input_messages,
                    tools=self._get_tools_schema(),
                )
            except Exception as e:
                _logger.error("API Call Error: %s", str(e))
                return f"Lỗi gọi OpenAI: {str(e)}"

            # Kiểm tra Output Message
            _logger.info("API Response Object: %s", str(response))
            try:
                _logger.info("API Response Dict: %s", response.to_dict())
            except:
                pass
            
            tool_calls = []
            output_text = ""

            # API Responses v2: response.output là list các item (text generated, function call, etc)
            if hasattr(response, 'output') and response.output:
                for item in response.output:
                    # 1. Text Output
                    if hasattr(item, 'type') and item.type == 'message':
                        # Item có thể là ResponseMessage?
                        # Trong log user gửi không thấy type='message' trong output list, mà là content list?
                        # Log mẫu: output=[ResponseFileSearchToolCall(...), ResponseFunctionToolCall(...)]
                        # Không thấy text. Có thể text nằm ở object khác hoặc user prompt chỉ trigger tool.
                        pass
                    
                    # Cấu trúc khác: item có thể là content block?
                    # Check các attribute thường gặp
                    if hasattr(item, 'content'):
                        # Nếu là message object
                        pass

                    # 2. Function Call (Tool)
                    if hasattr(item, 'type') and item.type == 'function_call':
                        # Map ResponseFunctionToolCall -> Standard Tool Call dict
                        tool_calls.append({
                            "id": item.call_id, # Lưu ý: dùng call_id (call_...) chứ không phải id (fc_...)
                            "type": "function",
                            "function": {
                                "name": item.name,
                                "arguments": item.arguments
                            }
                        })
                    
                    # 3. Text content (nếu item là text object?)
                    # Hiện tại chưa thấy mẫu text object trong log, nhưng nếu có sẽ xử lý sau.
                    # Nếu output là list các 'ResponseInputText' hay tương tự?
            
            # Fallback (Phòng hờ trường hợp cũ hoặc cấu trúc khác)
            if not tool_calls and not output_text:
                # Code cũ của output_message / tool_calls / output_text flat
                flat_tool_calls = getattr(response, 'tool_calls', [])
                if flat_tool_calls:
                   for tc in flat_tool_calls:
                       tool_calls.append({
                           "id": tc.id,
                           "type": tc.type,
                           "function": {
                               "name": tc.function.name,
                               "arguments": tc.function.arguments
                           }
                       })
                
                flat_text = getattr(response, 'output_text', None)
                if flat_text: output_text = flat_text

            # 1. Nếu có Tool Calls -> Thực hiện
            if tool_calls:
                # Append AI turn vào history
                ai_msg_dict = {
                    "role": "assistant",
                    "content": output_text or "", 
                }
                input_messages.append(ai_msg_dict)

                # Thực hiện từng Tool
                for tc in tool_calls:
                    fname = tc['function']['name']
                    call_id = tc['id']
                    args = json.loads(tc['function']['arguments'] or '{}')
                    
                    _logger.info("⚡ Tool Call: %s | Args: %s", fname, str(args))
                    tool_result_str = ""

                    # Dispatch through misa.crm.tools registry
                    tool_result_str = self.env['misa.crm.tools'].sudo().execute(fname, args)
                    
                    # Append Tool Output (biến tấu thành User role vì API Responses không chịu tool_calls input)
                    input_messages.append({
                        "role": "user",
                        "content": f"[System System] Executed Tool '{fname}': {tool_result_str}"
                    })
                
                # Loop tiếp để gửi kết quả tool lên AI
                continue
            
            else:
                # 2. Nếu không có Tool Call -> Đây là câu trả lời cuối cùng
                final_response_text = output_text
                break

        # Xóa các ký tự tham chiếu rác (VD: 【4:0†source】) của File Search
        final_response_text = re.sub(r'【.*?】', '', final_response_text)
        return final_response_text or "..."

    def _get_conversation_history(self):
        """Lấy 10 tin nhắn gần nhất từ DB để làm history context"""
        messages = self.env['hlv.chatgpt.message'].search([
            ('session_id', '=', self.id)
        ], order='create_date desc', limit=10)
        
        # Đảo ngược lại để đúng thứ tự thời gian (Cũ nhất -> Mới nhất)
        messages = messages.sorted(key=lambda r: r.create_date)
        
        history = []
        for msg in messages:
            # Chỉ lấy message Text đơn giản để tiết kiệm token và tránh lỗi format phức tạp
            # (Có thể nâng cấp để support multi-modal history sau)
            content_str = msg.content
            # Remove image link logs from content if exist to avoid confusion
            if "[IMG:" in content_str:
                content_str = content_str.split("\n[IMG:")[0]

            history.append({
                "role": msg.role,
                "content": content_str
            })
        return history

    def _download_image_to_base64(self, url):
        """Tải ảnh và convert sang base64 để gửi kèm message"""
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return base64.b64encode(response.content).decode('utf-8')
        except Exception as e:
            _logger.error("Download Image Error: %s", e)
        return None

    # =================================================================================
    # 2. IMPLEMENTATION (CÁC HÀM CÔNG CỤ - GIỮ NGUYÊN)
    # =================================================================================
    
    def _execute_get_category_info(self, args):
        """Tool: Lấy tên nhóm từ ID"""
        _logger.info("ℹ️ Check Category: %s", args)
        cat_id = args.get('category_id')
        if not cat_id: return json.dumps({"error": "Thiếu category_id"})

        try:
            misa_utils = self.env['misa.api.utils'].sudo()
            misa_config = self.env['misa.config'].sudo()
            token = misa_utils._fetch_login_crm_token()
            headers = misa_config.get_crm_header(token)
            real_name = misa_utils.get_category_name_by_id(headers, cat_id)
            
            return json.dumps({
                "category_id": cat_id,
                "category_name": real_name,
                "note": "Hãy dùng tên này để trả lời User."
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    def _execute_search_category_misa(self, args):
        """Tool: Tìm ID nhóm từ tên"""
        _logger.info("ℹ️ Search Category Data: %s", args)
        name = args.get('name')
        if not name: return json.dumps({"error": "Thiếu tên nhóm"})

        try:
            misa_utils = self.env['misa.api.utils'].sudo()
            misa_config = self.env['misa.config'].sudo()
            token = misa_utils._fetch_login_crm_token()
            headers = misa_config.get_crm_header(token)
            
            # Gọi hàm tìm ID từ tên trong Utils
            cat_id = misa_utils._get_category_id_by_name(headers, name)
            
            if cat_id:
                # Nếu tìm thấy ID, lấy luôn tên chuẩn để trả về
                real_name = misa_utils._get_category_name_by_id(headers, cat_id) or name
                return json.dumps({
                    "status": "found",
                    "category_id": cat_id,
                    "category_name": real_name,
                    "message": "Tìm thấy nhóm. Hãy dùng ID này để tạo sản phẩm."
                }, ensure_ascii=False)
            else:
                return json.dumps({
                    "status": "not_found",
                    "category_id": 2, # Fallback ID 2 (Danh mục khác)
                    "message": "Không tìm thấy nhóm này. Có thể dùng ID 2 (DANH MỤC KHÁC) hoặc tìm lại với từ khóa khác."
                }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": str(e)})

    def _execute_search_misa(self, args):
        """Tìm kiếm sản phẩm trong MISA (Live DB)"""
        _logger.info("🔍 MISA Search: %s", args)
        try:
            name = args.get('name')
            code = args.get('code')
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
        """Tạo 1 sản phẩm MISA (Single Object)"""
        _logger.info("🆕 MISA Create: %s", args)
        try:
            misa_utils = self.env['misa.api.utils'].sudo()
            misa_id = misa_utils.create_product_misa_raw(
                code=args.get('code'),
                name=args.get('name'),
                price=args.get('price', 0),
                tax_percent=args.get('tax', 10),
                unit_name=args.get('unit', 'Cái'),
                category_name=args.get('category', 'Hàng hóa'),
                product_type=args.get('type', 'goods'), 
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
    # 4. ZALO & UI INTEGRATION (GIỮ NGUYÊN LOGIC, CHỈ CẬP NHẬT CÁCH GỌI)
    # =================================================================================
    @api.model
    def process_zalo_message(self, zalo_user_id, message_content, zalo_msg_id=False, image_url=False):
        """Webhook Entry Point"""
        session = self.sudo().search([
            ('zalo_user_id', '=', zalo_user_id)
        ], limit=1, order='last_activity desc')

        if not session:
            session = self.sudo().create({
                'name': f'Zalo Chat - {zalo_user_id}',
                'zalo_user_id': zalo_user_id,
                'state': 'active'
            })

        # Persist last inbound message for operators
        session.sudo().write({
            'last_customer_message': (message_content or '[Gửi ảnh]')
        })

        display_content = message_content
        if image_url:
            display_content = f"{message_content or '[Gửi ảnh]'} \n[IMG: {image_url}]"

        self.env['hlv.chatgpt.message'].sudo().create({
            'session_id': session.id,
            'role': 'user',
            'content': display_content,
            'zalo_msg_id': zalo_msg_id
        })

        ai_reply = session._call_openai_api(message_content, image_url=image_url)

        # Persist last AI reply for operators
        session.sudo().write({
            'last_ai_reply': ai_reply
        })

        # Update editable summary/memory fields
        session._update_session_summary(message_content, ai_reply)

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
        
        self.env['hlv.chatgpt.message'].create({
            'session_id': self.id, 
            'role': 'user', 
            'content': self.input_text
        })
        
        response = self._call_openai_api(self.input_text)
        
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
    # Thêm 'tool' vào role nếu cần lưu lịch sử detailed, nhưng hiện tại chỉ lưu user/as
    role = fields.Selection([('user','User'),('assistant','AI'),('system','System'),('tool','Tool')], required=True)
    content = fields.Text(string="Nội dung")
    zalo_msg_id = fields.Char(string="Msg ID Zalo (Deduplication)")
