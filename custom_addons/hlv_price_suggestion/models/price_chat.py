import base64
import io
import json
import logging
from datetime import timedelta

import requests

from odoo import api, fields, models
from odoo.tools.translate import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# OpenAI Function Calling Tools — AI tự query Odoo
# ═══════════════════════════════════════════════════════════
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_product",
            "description": (
                "Tìm sản phẩm trong hệ thống Odoo. Hỗ trợ tìm theo mã SP (default_code), tên, "
                "hoặc từ khóa gợi nhớ. Tool tự động tách keyword và tìm nhiều cách.\n"
                "VÍ DỤ CÁCH DÙNG:\n"
                "- User nói 'Contactor Fuji 110V' → keyword='Contactor Fuji 110V'\n"
                "- User nói 'SC-5-1' → keyword='SC-5-1'\n"
                "- User nói 'contactor SC-N1 Fuji' → keyword='SC-N1'\n"
                "MẸO: Nếu không tìm thấy, thử lại với keyword ngắn hơn (chỉ mã SP)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Mã sản phẩm, tên, hoặc từ khóa gợi nhớ. Có thể dùng 1 phần mã (VD: 'SC-5-1' thay vì 'SC-5-1-110V-FUJI')",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_purchase_history",
            "description": (
                "Lấy lịch sử mua hàng (Purchase Order) của sản phẩm. "
                "Trả về các đơn PO đã xác nhận, giá nhập, nhà cung cấp, ngày mua."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "ID sản phẩm (lấy từ search_product)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Số đơn PO tối đa cần lấy (mặc định 15)",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sale_history",
            "description": (
                "Lấy lịch sử bán hàng (Sale Order) của sản phẩm. "
                "Có thể lọc theo tên khách hàng/công ty cụ thể. "
                "Trả về đơn SO đã xác nhận, giá bán, khách hàng, công ty, ngày bán."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "ID sản phẩm (lấy từ search_product)",
                    },
                    "customer_keyword": {
                        "type": "string",
                        "description": "Tên khách hàng hoặc công ty để lọc (VD: 'VMEP', 'Hòa Phát'). Để trống = lấy tất cả.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Số đơn SO tối đa (mặc định 20)",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_info",
            "description": (
                "Lấy thông tin tồn kho của sản phẩm. "
                "Trả về tổng tồn, sẵn sàng, đã đặt, chi tiết theo từng kho."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "ID sản phẩm",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sales_velocity",
            "description": (
                "Lấy tốc độ bán hàng của sản phẩm trong N ngày gần đây. "
                "Trả về tổng đã bán, trung bình/ngày, số đơn, ước tính ngày tồn kho còn."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "ID sản phẩm",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Số ngày (mặc định 30)",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_customer",
            "description": (
                "Tìm khách hàng / công ty trong hệ thống theo tên. "
                "Trả về danh sách khách hàng khớp."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Tên khách hàng hoặc công ty để tìm (VD: 'VMEP', 'Hòa Phát')",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_order_history",
            "description": (
                "Lấy lịch sử đơn hàng của một khách hàng cụ thể. "
                "Có thể lọc theo sản phẩm. Trả về các đơn SO, sản phẩm, giá, ngày."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "partner_id": {
                        "type": "integer",
                        "description": "ID khách hàng (lấy từ search_customer)",
                    },
                    "product_id": {
                        "type": "integer",
                        "description": "ID sản phẩm để lọc (tùy chọn)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Số đơn tối đa (mặc định 20)",
                    },
                },
                "required": ["partner_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_pricelist",
            "description": (
                "Lấy giá bán hiện tại của sản phẩm từ bảng giá (pricelist). "
                "Trả về list price, cost price, và giá từ các bảng giá."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "ID sản phẩm",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
]


class PriceChatSession(models.Model):
    _name = 'price.chat.session'
    _description = 'Phiên chat tư vấn giá'
    _order = 'create_date desc'

    name = fields.Char(
        string='Tiêu đề', default=lambda self: _('Phiên tư vấn giá mới'),
    )
    message_ids = fields.One2many(
        'price.chat.message', 'session_id', string='Tin nhắn',
    )
    user_id = fields.Many2one(
        'res.users', string='Người dùng',
        default=lambda self: self.env.user, readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Công ty',
        default=lambda self: self.env.company,
    )

    def _get_config(self):
        return self.env['price.chat.config'].get_config()

    # ════════════════════════════════════════════
    # RPC endpoints (gọi từ JS)
    # ════════════════════════════════════════════
    @api.model
    def rpc_send_message(self, session_id, message):
        """RPC endpoint cho OWL chat component."""
        session = self.browse(session_id)
        if not session.exists():
            raise UserError(_('Phiên chat không tồn tại.'))

        user_text = (message or '').strip()
        if not user_text:
            raise UserError(_('Tin nhắn không được để trống.'))

        self.env['price.chat.message'].create({
            'session_id': session.id,
            'role': 'user',
            'content': user_text,
        })

        try:
            ai_response = session._run_agent(user_text)
        except UserError:
            raise
        except Exception as e:
            _logger.exception('Price chat AI error')
            ai_response = _('Xin lỗi, đã có lỗi xảy ra: %s') % str(e)

        self.env['price.chat.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': ai_response,
        })

        if session.name == _('Phiên tư vấn giá mới') and len(session.message_ids) <= 2:
            session.name = user_text[:80]

        return {'ai_response': ai_response}

    @api.model
    def rpc_process_excel(self, session_id, base64_data, file_name):
        """RPC: nhận file Excel, trích mã SP, gọi AI agent."""
        session = self.browse(session_id)
        if not session.exists():
            raise UserError(_('Phiên chat không tồn tại.'))

        try:
            import openpyxl
        except ImportError:
            raise UserError(_('Cần cài thư viện openpyxl.'))

        try:
            file_bytes = base64.b64decode(base64_data)
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        except Exception as e:
            raise UserError(_('Không thể đọc file Excel: %s') % str(e))

        product_keywords = set()
        for ws in wb.worksheets:
            for row in ws.iter_rows(max_row=500, values_only=True):
                for cell_value in row:
                    if cell_value and isinstance(cell_value, str):
                        val = cell_value.strip()
                        if 2 <= len(val) <= 100:
                            product_keywords.add(val)
                    elif cell_value and isinstance(cell_value, (int, float)):
                        val = str(int(cell_value)).strip()
                        if len(val) >= 3:
                            product_keywords.add(val)
        wb.close()

        if not product_keywords:
            raise UserError(_('Không tìm thấy mã/tên sản phẩm trong file Excel.'))

        keywords_list = list(product_keywords)[:30]
        product_list_str = ', '.join(keywords_list[:20])
        if len(keywords_list) > 20:
            product_list_str += f'... (tổng {len(keywords_list)} mã)'

        user_msg = f'📎 File: {file_name}\nMã sản phẩm: {product_list_str}'
        self.env['price.chat.message'].create({
            'session_id': session.id,
            'role': 'user',
            'content': user_msg,
        })

        question = (
            f'Phân tích và đề xuất giá cho các sản phẩm từ file Excel "{file_name}". '
            f'Danh sách mã/tên cần tra: {product_list_str}. '
            f'Hãy dùng tool search_product cho từng mã, rồi get_purchase_history, '
            f'get_sale_history, get_stock_info để thu thập dữ liệu và đề xuất giá.'
        )

        try:
            ai_response = session._run_agent(question)
        except UserError:
            raise
        except Exception as e:
            _logger.exception('Price chat Excel AI error')
            ai_response = _('Xin lỗi, đã có lỗi xảy ra: %s') % str(e)

        self.env['price.chat.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': ai_response,
        })

        if session.name == _('Phiên tư vấn giá mới'):
            session.name = f'Excel: {file_name}'[:80]

        return {'ai_response': ai_response}

    # ════════════════════════════════════════════
    # AI Agent — Function Calling Loop
    # ════════════════════════════════════════════
    def _run_agent(self, user_question):
        """
        Chạy AI agent với function calling loop.
        AI tự quyết định cần query gì → gọi tool → nhận kết quả → trả lời.
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        api_key = ICP.get_param('openai.api_key')
        if not api_key:
            raise UserError(_(
                'Chưa cấu hình OpenAI API Key.\n'
                'Vào Settings → Technical → System Parameters → tạo key "openai.api_key"'
            ))

        config = self._get_config()
        ai_model = config.ai_model or 'gpt-4o-mini'
        max_tokens = config.max_tokens or 2000
        temperature = config.temperature or 0.3
        system_prompt = config.system_prompt or 'Bạn là chuyên gia tư vấn giá bán sản phẩm.'

        # Lấy lịch sử chat
        history = []
        recent_msgs = self.message_ids.sorted('create_date')[-10:]
        for msg in recent_msgs:
            history.append({'role': msg.role, 'content': msg.content})

        messages = [{'role': 'system', 'content': system_prompt}]
        messages.extend(history)
        messages.append({'role': 'user', 'content': user_question})

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }

        # Function calling loop — max 10 vòng
        for iteration in range(10):
            try:
                payload = {
                    'model': ai_model,
                    'messages': messages,
                    'max_tokens': max_tokens,
                    'temperature': temperature,
                    'tools': TOOL_DEFINITIONS,
                    'tool_choice': 'auto',
                }
                response = requests.post(
                    'https://api.openai.com/v1/chat/completions',
                    headers=headers,
                    json=payload,
                    timeout=90,
                )
                response.raise_for_status()
                result = response.json()
                choice = result['choices'][0]
                assistant_msg = choice['message']

                # Nếu AI muốn gọi tool
                tool_calls = assistant_msg.get('tool_calls')
                if tool_calls:
                    # Append assistant message (with tool_calls)
                    messages.append(assistant_msg)

                    # Xử lý từng tool call
                    for tc in tool_calls:
                        fn_name = tc['function']['name']
                        fn_args_str = tc['function'].get('arguments', '{}')
                        try:
                            fn_args = json.loads(fn_args_str)
                        except json.JSONDecodeError:
                            fn_args = {}

                        _logger.info(
                            'AI tool call [%s]: %s(%s)',
                            iteration, fn_name, json.dumps(fn_args, ensure_ascii=False),
                        )

                        # Thực thi tool
                        tool_result = self._execute_tool(fn_name, fn_args)
                        tool_result_str = json.dumps(tool_result, ensure_ascii=False, default=str)

                        # Truncate nếu quá dài
                        if len(tool_result_str) > 8000:
                            tool_result_str = tool_result_str[:8000] + '\n... (đã cắt bớt)'

                        messages.append({
                            'role': 'tool',
                            'tool_call_id': tc['id'],
                            'content': tool_result_str,
                        })

                    # Tiếp tục loop để AI xử lý kết quả tool
                    continue

                # AI trả lời cuối cùng (không gọi tool nữa)
                if choice.get('finish_reason') == 'stop' or assistant_msg.get('content'):
                    return assistant_msg.get('content', _('AI không trả lời.'))

            except requests.exceptions.Timeout:
                raise UserError(_('Kết nối OpenAI bị timeout. Vui lòng thử lại.'))
            except requests.exceptions.RequestException as e:
                _logger.error('OpenAI API error: %s', e)
                raise UserError(_('Lỗi kết nối OpenAI: %s') % str(e))
            except (KeyError, IndexError) as e:
                _logger.error('OpenAI response parse error: %s', e)
                raise UserError(_('Không thể phân tích phản hồi từ AI.'))

        return _('AI đã thực hiện quá nhiều bước query. Vui lòng hỏi cụ thể hơn.')

    # ════════════════════════════════════════════
    # Tool Implementations (AI gọi)
    # ════════════════════════════════════════════
    def _execute_tool(self, fn_name, args):
        """Dispatch tool call tới method tương ứng."""
        tool_map = {
            'search_product': self._tool_search_product,
            'get_purchase_history': self._tool_get_purchase_history,
            'get_sale_history': self._tool_get_sale_history,
            'get_stock_info': self._tool_get_stock_info,
            'get_sales_velocity': self._tool_get_sales_velocity,
            'search_customer': self._tool_search_customer,
            'get_customer_order_history': self._tool_get_customer_order_history,
            'get_product_pricelist': self._tool_get_product_pricelist,
        }

        fn = tool_map.get(fn_name)
        if not fn:
            return {'error': f'Tool "{fn_name}" không tồn tại'}

        try:
            return fn(**args)
        except Exception as e:
            _logger.exception('Tool %s error', fn_name)
            return {'error': str(e)}

    def _tool_search_product(self, keyword, **kw):
        """Tìm sản phẩm — multi-strategy: exact → ilike → từng từ → partial code."""
        Product = self.env['product.product'].sudo()
        keyword = (keyword or '').strip()
        if not keyword:
            return {'total_found': 0, 'products': [], 'hint': 'Keyword trống'}

        found = Product.browse()

        # Strategy 1: Exact match trên default_code
        exact = Product.search([('default_code', '=ilike', keyword)], limit=10)
        found |= exact

        # Strategy 2: ilike trên cả code + name
        if len(found) < 10:
            ilike = Product.search([
                '|',
                ('default_code', 'ilike', keyword),
                ('name', 'ilike', keyword),
            ], limit=15)
            found |= ilike

        # Strategy 3: Tách keyword thành từng phần và tìm mỗi phần
        if not found:
            # Tách theo dấu cách, gạch ngang, gạch dưới
            import re
            parts = re.split(r'[\s,;]+', keyword)
            # Lọc bỏ stop words tiếng Việt phổ biến
            stop_words = {
                'bán', 'mua', 'giá', 'cho', 'của', 'và', 'với', 'là', 'này',
                'cái', 'chiếc', 'con', 'bộ', 'cây', 'hộp', 'bao', 'nhiêu',
                'nên', 'thì', 'được', 'không', 'có', 'tôi', 'sản', 'phẩm',
                'the', 'and', 'for', 'how', 'much', 'price',
            }
            parts = [p for p in parts if len(p) >= 2 and p.lower() not in stop_words]

            if len(parts) >= 2:
                # Tìm sản phẩm chứa TẤT CẢ các từ (AND logic)
                domain = []
                for part in parts[:5]:  # Tối đa 5 từ
                    domain.append('|')
                    domain.append(('default_code', 'ilike', part))
                    domain.append(('name', 'ilike', part))
                # Tìm rồi lọc lại: chỉ giữ SP chứa nhiều từ nhất
                candidates = Product.search(domain, limit=50)
                if candidates:
                    scored = []
                    for p in candidates:
                        text = f"{p.default_code or ''} {p.name}".lower()
                        score = sum(1 for part in parts if part.lower() in text)
                        scored.append((score, p))
                    scored.sort(key=lambda x: x[0], reverse=True)
                    best_score = scored[0][0]
                    found |= Product.browse([p.id for s, p in scored if s >= best_score][:15])
            elif parts:
                # Một từ duy nhất có nghĩa
                single = parts[0]
                found |= Product.search([
                    '|',
                    ('default_code', 'ilike', single),
                    ('name', 'ilike', single),
                ], limit=15)

        # Strategy 4: Tìm theo barcode
        if not found:
            barcode_match = Product.search([('barcode', 'ilike', keyword)], limit=5)
            found |= barcode_match

        products = found[:20]
        result = {
            'total_found': len(products),
            'products': [{
                'id': p.id,
                'default_code': p.default_code or '',
                'name': p.name,
                'list_price': p.lst_price,
                'standard_price': p.standard_price,
                'type': p.type,
                'categ': p.categ_id.complete_name or '',
                'active': p.active,
            } for p in products],
        }

        if not products:
            result['hint'] = (
                f'Không tìm thấy sản phẩm với "{keyword}". '
                'Thử search lại với từ khóa ngắn hơn hoặc chỉ dùng mã SP (VD: SC-5-1).'
            )

        return result

    def _tool_get_purchase_history(self, product_id, limit=15, **kw):
        """Lấy lịch sử mua hàng PO."""
        po_lines = self.env['purchase.order.line'].sudo().search([
            ('product_id', '=', product_id),
            ('order_id.state', 'in', ('purchase', 'done')),
        ], order='create_date desc', limit=limit)

        if not po_lines:
            return {'message': 'Không tìm thấy đơn mua hàng nào cho sản phẩm này.', 'orders': []}

        # Tính giá nhập trung bình
        total_cost = sum(l.price_unit * l.product_qty for l in po_lines)
        total_qty = sum(l.product_qty for l in po_lines)
        avg_price = round(total_cost / total_qty, 0) if total_qty else 0

        return {
            'avg_purchase_price': avg_price,
            'total_orders': len(po_lines),
            'orders': [{
                'po_name': l.order_id.name,
                'date': str(l.order_id.date_order or l.create_date)[:10],
                'vendor': l.order_id.partner_id.name,
                'unit_price': l.price_unit,
                'qty': l.product_qty,
                'total': round(l.price_unit * l.product_qty, 0),
                'currency': l.currency_id.name or 'VND',
            } for l in po_lines],
        }

    def _tool_get_sale_history(self, product_id, customer_keyword=None, limit=20, **kw):
        """Lấy lịch sử bán hàng SO, có thể lọc theo khách hàng."""
        domain = [
            ('product_id', '=', product_id),
            ('order_id.state', 'in', ('sale', 'done')),
        ]

        if customer_keyword:
            # Tìm partner trước
            partners = self.env['res.partner'].sudo().search([
                ('name', 'ilike', customer_keyword),
            ], limit=20)
            if partners:
                domain.append(('order_id.partner_id', 'in', partners.ids))
            else:
                return {
                    'message': f'Không tìm thấy khách hàng "{customer_keyword}" trong hệ thống.',
                    'orders': [],
                }

        so_lines = self.env['sale.order.line'].sudo().search(
            domain, order='create_date desc', limit=limit,
        )

        if not so_lines:
            msg = 'Không tìm thấy đơn bán hàng nào'
            if customer_keyword:
                msg += f' cho khách hàng "{customer_keyword}"'
            return {'message': msg + '.', 'orders': []}

        # Giá bán trung bình
        total_revenue = sum(l.price_unit * l.product_uom_qty for l in so_lines)
        total_qty = sum(l.product_uom_qty for l in so_lines)
        avg_price = round(total_revenue / total_qty, 0) if total_qty else 0

        # Giá min/max
        prices = [l.price_unit for l in so_lines if l.price_unit > 0]
        min_price = min(prices) if prices else 0
        max_price = max(prices) if prices else 0

        return {
            'avg_sale_price': avg_price,
            'min_price': min_price,
            'max_price': max_price,
            'total_orders': len(so_lines),
            'orders': [{
                'so_name': l.order_id.name,
                'date': str(l.order_id.date_order)[:10],
                'customer': l.order_id.partner_id.name,
                'company': l.order_id.company_id.name,
                'unit_price': l.price_unit,
                'qty': l.product_uom_qty,
                'discount': l.discount,
                'total': round(l.price_subtotal, 0),
            } for l in so_lines],
        }

    def _tool_get_stock_info(self, product_id, **kw):
        """Lấy thông tin tồn kho."""
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product_id),
            ('location_id.usage', '=', 'internal'),
        ])

        total = sum(q.quantity for q in quants)
        reserved = sum(q.reserved_quantity for q in quants)
        available = total - reserved

        # Chi tiết theo kho
        wh_detail = {}
        for q in quants:
            wh_name = q.location_id.warehouse_id.name or q.location_id.complete_name
            if wh_name not in wh_detail:
                wh_detail[wh_name] = {'total': 0, 'reserved': 0, 'available': 0}
            wh_detail[wh_name]['total'] += q.quantity
            wh_detail[wh_name]['reserved'] += q.reserved_quantity
            wh_detail[wh_name]['available'] += q.quantity - q.reserved_quantity

        return {
            'total_qty': total,
            'reserved_qty': reserved,
            'available_qty': available,
            'warehouses': wh_detail,
        }

    def _tool_get_sales_velocity(self, product_id, days=30, **kw):
        """Lấy tốc độ bán hàng trong N ngày."""
        date_from = fields.Datetime.now() - timedelta(days=days)
        so_lines = self.env['sale.order.line'].sudo().search([
            ('product_id', '=', product_id),
            ('order_id.state', 'in', ('sale', 'done')),
            ('order_id.date_order', '>=', date_from),
        ])

        total_sold = sum(l.qty_delivered for l in so_lines)
        total_ordered = sum(l.product_uom_qty for l in so_lines)
        num_orders = len(so_lines.mapped('order_id'))
        avg_daily = round(total_sold / days, 2) if days > 0 else 0

        # Ước tính ngày tồn kho còn
        stock_info = self._tool_get_stock_info(product_id)
        available = stock_info.get('available_qty', 0)
        days_left = round(available / avg_daily, 1) if avg_daily > 0 else None

        return {
            'period_days': days,
            'total_delivered': total_sold,
            'total_ordered': total_ordered,
            'num_orders': num_orders,
            'avg_daily_sold': avg_daily,
            'current_stock_available': available,
            'estimated_days_left': days_left if days_left is not None else 'Không bán gần đây - không ước tính được',
        }

    def _tool_search_customer(self, keyword, **kw):
        """Tìm khách hàng theo tên."""
        partners = self.env['res.partner'].sudo().search([
            '|',
            ('name', 'ilike', keyword),
            ('ref', 'ilike', keyword),
            ('customer_rank', '>', 0),
        ], limit=10, order='customer_rank desc, name')

        if not partners:
            # Thử search rộng hơn (bỏ filter customer_rank)
            partners = self.env['res.partner'].sudo().search([
                '|',
                ('name', 'ilike', keyword),
                ('ref', 'ilike', keyword),
            ], limit=10, order='name')

        return {
            'total_found': len(partners),
            'customers': [{
                'id': p.id,
                'name': p.name,
                'ref': p.ref or '',
                'email': p.email or '',
                'phone': p.phone or '',
                'city': p.city or '',
                'is_company': p.is_company,
            } for p in partners],
        }

    def _tool_get_customer_order_history(self, partner_id, product_id=None, limit=20, **kw):
        """Lấy lịch sử đơn hàng của khách hàng."""
        domain = [
            ('order_id.partner_id', '=', partner_id),
            ('order_id.state', 'in', ('sale', 'done')),
        ]
        if product_id:
            domain.append(('product_id', '=', product_id))

        so_lines = self.env['sale.order.line'].sudo().search(
            domain, order='create_date desc', limit=limit,
        )

        if not so_lines:
            return {'message': 'Không tìm thấy đơn hàng.', 'orders': []}

        return {
            'total_orders': len(so_lines),
            'orders': [{
                'so_name': l.order_id.name,
                'date': str(l.order_id.date_order)[:10],
                'product_code': l.product_id.default_code or '',
                'product_name': l.product_id.name,
                'unit_price': l.price_unit,
                'qty': l.product_uom_qty,
                'discount': l.discount,
                'total': round(l.price_subtotal, 0),
                'company': l.order_id.company_id.name,
            } for l in so_lines],
        }

    def _tool_get_product_pricelist(self, product_id, **kw):
        """Lấy thông tin giá từ bảng giá."""
        product = self.env['product.product'].sudo().browse(product_id)
        if not product.exists():
            return {'error': 'Sản phẩm không tồn tại'}

        result = {
            'product_name': product.display_name,
            'list_price': product.lst_price,
            'standard_price': product.standard_price,
        }

        # Lấy giá từ các pricelist
        pricelists = self.env['product.pricelist'].sudo().search([], limit=10)
        pricelist_data = []
        for pl in pricelists:
            try:
                price = pl._get_product_price(product, 1.0)
                pricelist_data.append({
                    'pricelist_name': pl.name,
                    'currency': pl.currency_id.name,
                    'price': price,
                })
            except Exception:
                pass

        result['pricelists'] = pricelist_data
        return result

    # ════════════════════════════════════════════
    # Excel export (giữ lại)
    # ════════════════════════════════════════════
    def _generate_excel_data(self):
        """Thu thập data cho xuất Excel."""
        self.ensure_one()

        all_products = self.env['product.product']
        for msg in self.message_ids.filtered(lambda m: m.role == 'user'):
            words = msg.content.split()
            for word in words:
                if len(word) < 2:
                    continue
                matches = self.env['product.product'].search([
                    '|',
                    ('default_code', 'ilike', word),
                    ('name', 'ilike', word),
                ], limit=10)
                all_products |= matches

        result = []
        for product in all_products[:20]:
            info = {
                'san_pham': product.display_name,
                'ma_sp': product.default_code or '',
                'gia_ban_hien_tai': product.lst_price,
                'gia_nhap': [],
                'gia_ban_theo_cty': [],
                'ton_kho': self._tool_get_stock_info(product.id),
                'luot_ban_30_ngay': self._tool_get_sales_velocity(product.id),
            }
            po_data = self._tool_get_purchase_history(product.id)
            for o in po_data.get('orders', []):
                info['gia_nhap'].append({
                    'don_hang': o['po_name'],
                    'ngay': o['date'],
                    'nha_cung_cap': o['vendor'],
                    'gia': o['unit_price'],
                    'so_luong': o['qty'],
                })
            so_data = self._tool_get_sale_history(product.id)
            for o in so_data.get('orders', []):
                info.setdefault('gia_ban_theo_cty', [])
                info['gia_ban_theo_cty'].append({
                    'cong_ty': o['company'],
                    'don_hang': [{
                        'don_hang': o['so_name'],
                        'ngay': o['date'],
                        'khach_hang': o['customer'],
                        'gia_ban': o['unit_price'],
                        'so_luong': o['qty'],
                        'chiet_khau': o['discount'],
                    }],
                })
            result.append(info)
        return result


class PriceChatMessage(models.Model):
    _name = 'price.chat.message'
    _description = 'Tin nhắn chat tư vấn giá'
    _order = 'create_date asc'

    session_id = fields.Many2one(
        'price.chat.session', string='Phiên chat',
        required=True, ondelete='cascade',
    )
    role = fields.Selection([
        ('user', 'Người dùng'),
        ('assistant', 'AI'),
    ], string='Vai trò', required=True)
    content = fields.Text(string='Nội dung', required=True)
