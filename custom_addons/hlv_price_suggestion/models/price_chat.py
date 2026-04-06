import json
import logging
from datetime import timedelta

import requests

from odoo import api, fields, models
from odoo.tools.translate import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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

    @api.model
    def rpc_send_message(self, session_id, message):
        """RPC endpoint cho OWL chat component."""
        session = self.browse(session_id)
        if not session.exists():
            raise UserError(_('Phiên chat không tồn tại.'))

        user_text = (message or '').strip()
        if not user_text:
            raise UserError(_('Tin nhắn không được để trống.'))

        # Lưu tin nhắn user
        self.env['price.chat.message'].create({
            'session_id': session.id,
            'role': 'user',
            'content': user_text,
        })

        # Xử lý & gọi AI
        try:
            ai_response = session._process_question(user_text)
        except UserError:
            raise
        except Exception as e:
            _logger.exception('Price chat AI error')
            ai_response = _('Xin lỗi, đã có lỗi xảy ra: %s') % str(e)

        # Lưu tin nhắn AI
        self.env['price.chat.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': ai_response,
        })

        # Cập nhật tiêu đề phiên nếu là tin nhắn đầu
        if session.name == _('Phiên tư vấn giá mới') and len(session.message_ids) <= 2:
            session.name = user_text[:80]

        return {'ai_response': ai_response}

    # ────────────────────────────────────────────
    # Core AI logic
    # ────────────────────────────────────────────
    def _process_question(self, question):
        """Thu thập data, gọi AI, trả về phản hồi có lý luận."""
        self.ensure_one()

        # 1. Tìm sản phẩm liên quan từ câu hỏi
        products = self._find_products_from_question(question)

        # 2. Thu thập dữ liệu thực tế
        data_context = self._collect_all_data(products)

        # 3. Gọi OpenAI
        return self._call_openai(question, data_context)

    def _find_products_from_question(self, question):
        """Tìm sản phẩm dựa trên câu hỏi."""
        Product = self.env['product.product']

        # Thử tìm theo tên / mã sản phẩm
        words = question.split()
        found = Product.browse()

        for word in words:
            if len(word) < 2:
                continue
            matches = Product.search([
                '|',
                ('default_code', 'ilike', word),
                ('name', 'ilike', word),
                ('type', 'in', ('product', 'consu')),
            ], limit=10)
            found |= matches

        # Nếu không tìm thấy, thử tìm theo cụm 2−3 từ
        if not found:
            for i in range(len(words) - 1):
                phrase = ' '.join(words[i:i+2])
                matches = Product.search([
                    ('name', 'ilike', phrase),
                    ('type', 'in', ('product', 'consu')),
                ], limit=5)
                found |= matches

        return found[:20]  # Giới hạn 20 sản phẩm

    def _collect_all_data(self, products):
        """Thu thập toàn bộ dữ liệu cho các sản phẩm."""
        result = []
        for product in products:
            info = self._collect_product_data(product)
            result.append(info)
        return result

    def _collect_product_data(self, product):
        """Thu thập dữ liệu 1 sản phẩm: giá nhập, giá bán từng công ty, tồn kho, lượt bán."""
        data = {
            'san_pham': product.display_name,
            'ma_sp': product.default_code or '',
            'gia_ban_hien_tai': product.lst_price,
        }

        # ── Giá nhập từ PO (10 đơn gần nhất) ──
        po_lines = self.env['purchase.order.line'].sudo().search([
            ('product_id', '=', product.id),
            ('order_id.state', 'in', ('purchase', 'done')),
        ], order='create_date desc', limit=10)

        data['gia_nhap'] = []
        for pol in po_lines:
            data['gia_nhap'].append({
                'don_hang': pol.order_id.name,
                'ngay': str(pol.order_id.date_order or pol.create_date)[:10],
                'nha_cung_cap': pol.order_id.partner_id.name,
                'gia': pol.price_unit,
                'so_luong': pol.product_qty,
            })

        # ── Giá bán cho từng công ty (từ SO, 10 đơn gần nhất mỗi công ty) ──
        companies = self.env['res.company'].sudo().search([])
        data['gia_ban_theo_cty'] = []
        for company in companies:
            so_lines = self.env['sale.order.line'].sudo().search([
                ('product_id', '=', product.id),
                ('order_id.state', 'in', ('sale', 'done')),
                ('order_id.company_id', '=', company.id),
            ], order='create_date desc', limit=10)

            if not so_lines:
                continue

            orders_data = []
            for sol in so_lines:
                orders_data.append({
                    'don_hang': sol.order_id.name,
                    'ngay': str(sol.order_id.date_order)[:10],
                    'khach_hang': sol.order_id.partner_id.name,
                    'gia_ban': sol.price_unit,
                    'so_luong': sol.product_uom_qty,
                    'chiet_khau': sol.discount,
                })

            data['gia_ban_theo_cty'].append({
                'cong_ty': company.name,
                'don_hang': orders_data,
            })

        # ── Tồn kho ──
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id),
            ('location_id.usage', '=', 'internal'),
        ])
        data['ton_kho'] = {
            'tong': sum(q.quantity for q in quants),
            'san_sang': sum(q.quantity - q.reserved_quantity for q in quants),
            'da_dat': sum(q.reserved_quantity for q in quants),
        }

        # Chi tiết theo kho
        wh_detail = {}
        for q in quants:
            wh_name = q.location_id.warehouse_id.name or q.location_id.complete_name
            wh_detail.setdefault(wh_name, 0)
            wh_detail[wh_name] += q.quantity
        data['ton_kho']['chi_tiet_kho'] = wh_detail

        # ── Lượt bán 30 ngày ──
        date_30 = fields.Datetime.now() - timedelta(days=30)
        sol_30 = self.env['sale.order.line'].sudo().search([
            ('product_id', '=', product.id),
            ('order_id.state', 'in', ('sale', 'done')),
            ('order_id.date_order', '>=', date_30),
        ])
        total_sold_30d = sum(l.qty_delivered for l in sol_30)
        data['luot_ban_30_ngay'] = {
            'tong_da_ban': total_sold_30d,
            'trung_binh_ngay': round(total_sold_30d / 30.0, 2),
            'so_don': len(sol_30.mapped('order_id')),
        }

        # ── Ước tính ngày tồn kho còn ──
        avg_daily = total_sold_30d / 30.0
        stock_avail = data['ton_kho']['san_sang']
        if avg_daily > 0:
            data['so_ngay_ton_kho_con'] = round(stock_avail / avg_daily, 1)
        else:
            data['so_ngay_ton_kho_con'] = 'Không bán (không ước tính được)'

        return data

    def _call_openai(self, question, data_context):
        """Gọi OpenAI API để phân tích và đề xuất giá."""
        ICP = self.env['ir.config_parameter'].sudo()
        api_key = ICP.get_param('openai.api_key')

        if not api_key:
            raise UserError(_(
                'Chưa cấu hình OpenAI API Key.\n'
                'Vào Settings → Technical → System Parameters → tạo key "openai.api_key"'
            ))

        ai_model = ICP.get_param('openai.model', 'gpt-4o-mini')

        system_prompt = """Bạn là chuyên gia tư vấn giá bán sản phẩm cho doanh nghiệp bán lẻ tại Việt Nam.

NHIỆM VỤ:
- Phân tích dữ liệu thực tế được cung cấp và đề xuất giá bán tối ưu
- LUÔN đưa ra căn cứ cụ thể từ data (tên đơn hàng, giá, số lượng)
- Giải thích lý luận rõ ràng

FORMAT TRẢ LỜI:
1. **Tóm tắt**: Đề xuất giá ngắn gọn
2. **Căn cứ giá nhập**: Liệt kê các đơn mua hàng cụ thể (PO name, giá, NCC)
3. **Căn cứ giá bán**: Giá đã bán cho từng công ty/khách hàng (SO name, giá)
4. **Tình hình kho**: Tồn kho, tốc độ bán, ước tính ngày còn hàng
5. **Phân tích & lý luận**: Giải thích tại sao đề xuất giá này
6. **Đề xuất giá**: Giá cụ thể (làm tròn hàng nghìn VND)

QUY TẮC:
- Giá đề xuất PHẢI cao hơn giá nhập (tối thiểu 10% margin)
- Bán chạy + tồn ít → tăng giá
- Nhà cung cấp có vẻ khan hiếm hàng → tăng giá
- Bán chậm + tồn nhiều → xem xét giảm giá
- Nếu không có data đủ, nói rõ thiếu gì
- Format số tiền theo VND: 1,000,000
- Trả lời bằng tiếng Việt"""

        data_str = json.dumps(data_context, ensure_ascii=False, indent=2) if data_context else 'Không tìm thấy sản phẩm phù hợp trong hệ thống.'

        # Lấy lịch sử chat (tối đa 10 tin nhắn gần nhất)
        history = []
        recent_msgs = self.message_ids.sorted('create_date')[-10:]
        for msg in recent_msgs:
            history.append({
                'role': msg.role,
                'content': msg.content,
            })

        messages = [{'role': 'system', 'content': system_prompt}]
        messages.extend(history)
        messages.append({
            'role': 'user',
            'content': f'{question}\n\n--- DỮ LIỆU TỪ HỆ THỐNG ---\n{data_str}',
        })

        try:
            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': ai_model,
                    'messages': messages,
                    'max_tokens': 2000,
                    'temperature': 0.3,
                },
                timeout=60,
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']

        except requests.exceptions.Timeout:
            raise UserError(_('Kết nối OpenAI bị timeout. Vui lòng thử lại.'))
        except requests.exceptions.RequestException as e:
            _logger.error('OpenAI API error: %s', e)
            raise UserError(_('Lỗi kết nối OpenAI: %s') % str(e))
        except (KeyError, IndexError) as e:
            _logger.error('OpenAI response parse error: %s', e)
            raise UserError(_('Không thể phân tích phản hồi từ AI.'))

    # ────────────────────────────────────────────
    # Excel export
    # ────────────────────────────────────────────
    def _generate_excel_data(self):
        """Thu thập data cho xuất Excel: tất cả sản phẩm đã hỏi trong phiên."""
        self.ensure_one()

        # Tìm tất cả sản phẩm đã đề cập trong phiên
        all_products = self.env['product.product']
        for msg in self.message_ids.filtered(lambda m: m.role == 'user'):
            products = self._find_products_from_question(msg.content)
            all_products |= products

        result = []
        for product in all_products:
            info = self._collect_product_data(product)
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
