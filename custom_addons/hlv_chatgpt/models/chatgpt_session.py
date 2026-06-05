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

TOOLS_SCHEMA = [
    {
      "type": "function",
      "description": "Search to see if a product already exists in the system using its name before creating a new one.",
      "name": "search_product_misa",
      "parameters": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string",
            "description": "Product name or keyword to search for (e.g., Khoan FPD3, Bulong M12)"
          }
        },
        "required": [
          "name"
        ],
        "additionalProperties": False
      },
      "strict": True
    },
    {
      "type": "function",
      "description": "Tạo sản phẩm mới vào hệ thống. CHỈ GỌI KHI NGƯỜI DÙNG ĐÃ XÁC NHẬN 'OK' HOẶC 'ĐỒNG Ý'.",
      "name": "create_product_misa",
      "parameters": {
        "type": "object",
        "properties": {
          "code": {
            "type": "string",
            "description": "Mã sản phẩm (Viết liền, in hoa, không dấu, VD: MAYKHOAN01)"
          },
          "name": {
            "type": "string",
            "description": "Tên sản phẩm chuẩn hóa đầy đủ (VD: Máy khoan Pin Milwaukee FPD3)"
          },
          "price": {
            "type": "number",
            "description": "Giá bán đề xuất (VNĐ). Để mặc định là  0."
          },
          "price_pu": {
            "type": "number",
            "description": "Gía mua VND. Nếu không được cung cấp để mặc định 0đ"
          },
          "tax": {
            "type": "number",
            "description": "Thuế VAT (thường là 8 hoặc 10)"
          },
          "unit": {
            "type": "string",
            "description": "Đơn vị tính (Cái, Bộ, Hộp, Chai...)"
          },
          "category": {
            "type": "string",
            "description": "Tên nhóm hàng (Lấy từ file category.json)"
          },
          "category_id": {
            "type": "integer",
            "description": "ID định danh của nhóm hàng (QUAN TRỌNG: Phải tra cứu chính xác số ID từ file category.json tương ứng với tên nhóm)"
          },
          "type": {
            "type": "string",
            "enum": [
              "goods",
              "service",
              "finished_product"
            ],
            "description": "Loại hàng hóa (Mặc định là 'goods')"
          },
          "Description": {
            "type": "string",
            "description": "Mô tả sản phẩm trên MISA CRM. Có thể truyền chuỗi JSON, ví dụ: {\"Vật liệu\" : \"Thép\"}"
          }
        },
        "required": [
          "code",
          "name",
          "price",
          "tax",
          "unit",
          "category",
          "category_id",
          "type",
          "price_pu"
        ],
        "additionalProperties": False
      },
      "strict": True
    },
    {
      "type": "function",
      "description": "Cập nhật thông tin sản phẩm trên MISA CRM. Cần có misa_id của sản phẩm.",
      "name": "update_product_misa",
      "parameters": {
        "type": "object",
        "properties": {
          "misa_id": {
            "type": "string",
            "description": "MISA product ID (ví dụ : 77449)"
          },
          "field": {
            "type": "string",
            "enum": [
              "name",
              "code",
              "Description"
            ],
            "description": "Trường cần cập nhật: name=tên, code=mã, Description=mô tả sản phẩm"
          },
          "new_value": {
            "type": "string",
            "description": "Giá trị mới. Với Description có thể là chuỗi JSON, ví dụ: {\"Vật liệu\" : \"Thép\"}"
          },
          "old_value": {
            "type": "string",
            "description": "Giá trị cũ để đối chứng"
          }
        },
        "required": [
          "misa_id",
          "field",
          "new_value",
          "old_value"
        ],
        "additionalProperties": False
      },
      "strict": True
    },
    {
      "type": "function",
      "description": "Lấy tên chính xác của nhóm sản phẩm từ ID. Dùng để kiểm tra (double check) ID nhóm.",
      "name": "get_category_info",
      "parameters": {
        "type": "object",
        "properties": {
          "category_id": {
            "type": "string",
            "description": "ID của nhóm sản phẩm (Ví dụ: 52, guid...)"
          }
        },
        "required": [
          "category_id"
        ]
      },
      "strict": False
    },
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
    {
      "type": "function",
      "description": "Tìm kiếm ID nhóm sản phẩm theo tên. Dùng khi người dùng yêu cầu nhóm cụ thể hoặc check nhóm.",
      "name": "search_category_misa",
      "parameters": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string",
            "description": "Tên nhóm cần tìm (VD: Vật tư khí nén, Bảo hộ lao động...)"
          }
        },
        "required": [
          "name"
        ]
      },
      "strict": False
    }
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

    def _run_gpt_prompt_workflow(self, client, user_query, prompt_id, image_url=False):
        """
        Workflow xử lý chính với client.responses.create:
        1. Xây dựng lịch sử hội thoại (Input Messages)
        2. Gọi API với Prompt đã lưu (Stored Prompt)
        3. Xử lý Tool Calls (Loop)
        """
        # _logger.info("🚀 Start Prompt Workflow | Has Image: %s", bool(image_url))

        # A. Xây dựng danh sách tin nhắn đầu vào (Conversation History + New Message)
        input_messages = self._get_conversation_history()
        
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
                    "image_url": f"data:image/jpeg;base64,{image_data}"
                })
             else:
                current_content.append({"type": "input_text", "text": "[System Error: Không tải được ảnh đính kèm]"})

        if current_content:
            input_messages.append({
                "role": "user",
                "content": current_content
            })

        # B. VÒNG LẶP XỬ LÝ (CALL -> TOOL -> CALL)
        # API Responses không dùng ThreadRun stateful như Assistant/Threads API cũ.
        # Ta cần tự quản lý loop tool calls.
        
        MAX_STEPS = 40 # Tránh loop vô tận
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
                    tools=TOOLS_SCHEMA, # Định nghĩa lại Tool schema để server biết tool nào khả dụng
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

                    if fname == "search_product_misa":
                        tool_result_str = self._execute_search_misa(args)
                    elif fname == "create_product_misa":
                        tool_result_str = self._execute_create_misa(args)
                    elif fname == "update_product_misa":
                        tool_result_str = self._execute_update_misa(args)
                    elif fname == "get_category_info":
                        tool_result_str = self._execute_get_category_info(args)
                    elif fname == "search_category_misa":
                        tool_result_str = self._execute_search_category_misa(args)
                    else:
                        tool_result_str = json.dumps({"error": f"Function {fname} chưa được hỗ trợ"})
                    
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
                description=args.get('Description') or args.get('description') or "",
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
    def _execute_update_misa(self, args):
        """Cập nhật 1 trường sản phẩm MISA."""
        _logger.info("✏️ MISA Update: %s", args)
        try:
            misa_id = args.get('misa_id')
            field = args.get('field')
            new_value = args.get('new_value')
            old_value = args.get('old_value')

            misa_utils = self.env['misa.api.utils'].sudo()
            ok = misa_utils.update_product_field_misa(
                misa_id, field, new_value, old_value,
            )
            if ok:
                return json.dumps({
                    "status": "success",
                    "message": f"Đã cập nhật {field} thành '{new_value}'",
                }, ensure_ascii=False)
            return json.dumps({
                "status": "error",
                "message": f"Không thể cập nhật {field} cho MISA ID {misa_id}",
            }, ensure_ascii=False)

        except Exception as e:
            _logger.exception("Update Misa Error")
            return json.dumps({"status": "error", "message": f"Lỗi cập nhật MISA: {str(e)}"}, ensure_ascii=False)

    def _try_lock_for_zalo_processing(self):
        """Return False if another webhook is already processing this session."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "SELECT id FROM hlv_chatgpt_session WHERE id = %s FOR UPDATE NOWAIT",
                    [self.id],
                )
            return True
        except Exception:
            _logger.info("Zalo Chat session %s is already processing", self.id)
            return False

    def _zalo_busy_reply(self, message_content):
        content = (message_content or "").strip() or "[Gửi ảnh]"
        return (
            f'Hiện có yêu cầu đang xử lý, chưa xử lý được yêu cầu "{content}". '
            "Vui lòng thử lại sau."
        )

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

        display_content = message_content
        if image_url:
            display_content = f"{message_content or '[Gửi ảnh]'} \n[IMG: {image_url}]"

        if not session._try_lock_for_zalo_processing():
            busy_reply = session._zalo_busy_reply(message_content)
            self.env['hlv.chatgpt.message'].sudo().create({
                'session_id': session.id,
                'role': 'user',
                'content': display_content,
                'zalo_msg_id': zalo_msg_id
            })
            self.env['hlv.chatgpt.message'].sudo().create({
                'session_id': session.id,
                'role': 'assistant',
                'content': busy_reply
            })
            session.sudo().write({'last_activity': fields.Datetime.now()})
            return busy_reply

        self.env['hlv.chatgpt.message'].sudo().create({
            'session_id': session.id,
            'role': 'user',
            'content': display_content,
            'zalo_msg_id': zalo_msg_id
        })

        ai_reply = session._call_openai_api(message_content, image_url=image_url)

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
