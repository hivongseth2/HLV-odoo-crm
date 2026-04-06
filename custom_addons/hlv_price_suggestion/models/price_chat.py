import base64
import io
import json
import logging
import re
from datetime import timedelta
from urllib.parse import quote_plus

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

    def _get_config(self):
        """Lấy cấu hình AI."""
        return self.env['price.chat.config'].get_config()

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

    @api.model
    def rpc_process_excel(self, session_id, base64_data, file_name):
        """RPC endpoint: nhận file Excel, trích mã SP, thu thập data, gọi AI."""
        session = self.browse(session_id)
        if not session.exists():
            raise UserError(_('Phiên chat không tồn tại.'))

        try:
            import openpyxl
        except ImportError:
            raise UserError(_('Cần cài thư viện openpyxl.'))

        # Decode & parse Excel
        try:
            file_bytes = base64.b64decode(base64_data)
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        except Exception as e:
            raise UserError(_('Không thể đọc file Excel: %s') % str(e))

        # Extract product codes/names from all sheets
        product_keywords = set()
        for ws in wb.worksheets:
            for row in ws.iter_rows(max_row=500, values_only=True):
                for cell_value in row:
                    if cell_value and isinstance(cell_value, str):
                        val = cell_value.strip()
                        if 2 <= len(val) <= 100:
                            product_keywords.add(val)
                    elif cell_value and isinstance(cell_value, (int, float)):
                        # Mã SP dạng số
                        val = str(int(cell_value)).strip()
                        if len(val) >= 3:
                            product_keywords.add(val)
        wb.close()

        if not product_keywords:
            raise UserError(_('Không tìm thấy mã/tên sản phẩm trong file Excel.'))

        # Tìm sản phẩm trong hệ thống
        Product = self.env['product.product']
        found_products = Product.browse()
        for keyword in list(product_keywords)[:100]:  # Giới hạn 100
            matches = Product.search([
                '|',
                ('default_code', '=ilike', keyword),
                ('name', 'ilike', keyword),
                ('type', 'in', ('product', 'consu')),
            ], limit=5)
            found_products |= matches
        found_products = found_products[:30]  # Giới hạn 30 SP

        # Lưu tin nhắn user
        product_list_str = ', '.join(product_keywords) if len(product_keywords) <= 20 else \
            ', '.join(list(product_keywords)[:20]) + f'... (tổng {len(product_keywords)} mã)'
        user_msg = f'📎 File: {file_name}\nMã sản phẩm tìm thấy: {product_list_str}'
        self.env['price.chat.message'].create({
            'session_id': session.id,
            'role': 'user',
            'content': user_msg,
        })

        # Thu thập data & gọi AI
        try:
            data_context = session._collect_all_data(found_products)
            question = (
                f'Phân tích và đề xuất giá cho các sản phẩm từ file Excel "{file_name}". '
                f'Tìm thấy {len(found_products)} sản phẩm trong hệ thống. '
                f'Hãy đề xuất giá bán cho từng sản phẩm.'
            )
            ai_response = session._call_openai(question, data_context)
        except UserError:
            raise
        except Exception as e:
            _logger.exception('Price chat Excel AI error')
            ai_response = _('Xin lỗi, đã có lỗi xảy ra khi xử lý file: %s') % str(e)

        # Lưu tin nhắn AI
        self.env['price.chat.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': ai_response,
        })

        # Cập nhật tiêu đề
        if session.name == _('Phiên tư vấn giá mới'):
            session.name = f'Excel: {file_name}'[:80]

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

        # 3. Crawl giá thị trường (nếu bật)
        market_data = self._crawl_market_prices(products)
        if market_data:
            for item in data_context:
                code = item.get('ma_sp', '')
                name = item.get('san_pham', '')
                for mk in market_data:
                    if mk.get('ma_sp') == code or mk.get('san_pham') == name:
                        item['gia_thi_truong'] = mk.get('ket_qua', [])

        # 4. Gọi OpenAI
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

    # ────────────────────────────────────────────
    # Market crawl
    # ────────────────────────────────────────────
    def _crawl_market_prices(self, products):
        """Crawl giá thị trường từ các website đã cấu hình."""
        self.ensure_one()
        config = self._get_config()
        if not config.market_crawl_enabled or not products:
            return []

        urls_text = (config.market_urls or '').strip()
        if not urls_text:
            return []

        base_urls = [u.strip() for u in urls_text.splitlines() if u.strip()]
        timeout = config.crawl_timeout or 10
        results = []

        for product in products[:5]:  # Giới hạn 5 SP để tránh quá lâu
            product_name = product.name or ''
            product_code = product.default_code or ''
            search_term = product_code if product_code else product_name

            market_results = []
            for base_url in base_urls:
                try:
                    crawl_data = self._crawl_single_site(base_url, search_term, timeout)
                    if crawl_data:
                        market_results.extend(crawl_data)
                except Exception as e:
                    _logger.warning('Market crawl failed for %s on %s: %s', search_term, base_url, e)

            results.append({
                'san_pham': product.display_name,
                'ma_sp': product_code,
                'ket_qua': market_results,
            })

        return results

    def _crawl_single_site(self, base_url, search_term, timeout):
        """Crawl 1 website, tìm sản phẩm và trả về danh sách giá."""
        results = []
        try:
            from lxml import html as lxml_html
        except ImportError:
            _logger.warning('lxml not available for market crawl')
            return results

        # Sanitize URL
        base_url = base_url.rstrip('/')
        encoded_term = quote_plus(search_term)

        # Thử các pattern search URL phổ biến
        search_urls = [
            f'{base_url}/?s={encoded_term}',
            f'{base_url}/search?q={encoded_term}',
            f'{base_url}/tim-kiem?q={encoded_term}',
        ]

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'vi-VN,vi;q=0.9',
        }

        for search_url in search_urls:
            try:
                resp = requests.get(search_url, headers=headers, timeout=timeout, verify=True)
                if resp.status_code != 200:
                    continue

                tree = lxml_html.fromstring(resp.content)

                # Tìm giá từ structured data (JSON-LD)
                json_ld_scripts = tree.xpath('//script[@type="application/ld+json"]/text()')
                for script_text in json_ld_scripts:
                    try:
                        ld_data = json.loads(script_text)
                        items = ld_data if isinstance(ld_data, list) else [ld_data]
                        for item in items:
                            if item.get('@type') == 'Product':
                                name = item.get('name', '')
                                offers = item.get('offers', {})
                                price = offers.get('price') or offers.get('lowPrice', '')
                                if name and price:
                                    results.append({
                                        'nguon': base_url,
                                        'ten_sp': name[:100],
                                        'gia': str(price),
                                    })
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        pass

                # Tìm giá từ common CSS selectors
                price_selectors = [
                    './/span[contains(@class,"price")]',
                    './/div[contains(@class,"price")]',
                    './/*[contains(@class,"product-price")]',
                    './/*[contains(@class,"woocommerce-Price-amount")]',
                ]
                name_selectors = [
                    './/h2[contains(@class,"product")]//a',
                    './/h3[contains(@class,"product")]//a',
                    './/*[contains(@class,"product-title")]//a',
                    './/*[contains(@class,"product-name")]//a',
                ]

                # Lấy tên sản phẩm
                product_names = []
                for sel in name_selectors:
                    elements = tree.xpath(sel)
                    for el in elements[:10]:
                        text = (el.text_content() or '').strip()
                        if text:
                            product_names.append(text[:100])

                # Lấy giá
                prices_found = []
                for sel in price_selectors:
                    elements = tree.xpath(sel)
                    for el in elements[:10]:
                        text = (el.text_content() or '').strip()
                        # Trích xuất số tiền
                        nums = re.findall(r'[\d,.]+', text)
                        if nums:
                            prices_found.append(nums[0])

                # Ghép tên + giá
                for i, name in enumerate(product_names[:5]):
                    price = prices_found[i] if i < len(prices_found) else ''
                    if price:
                        results.append({
                            'nguon': base_url,
                            'ten_sp': name,
                            'gia': price,
                        })

                if results:
                    break  # Đã tìm thấy, không cần thử URL khác

            except requests.exceptions.RequestException:
                continue

        return results[:5]  # Tối đa 5 kết quả mỗi site

    def _call_openai(self, question, data_context):
        """Gọi OpenAI API để phân tích và đề xuất giá."""
        ICP = self.env['ir.config_parameter'].sudo()
        api_key = ICP.get_param('openai.api_key')

        if not api_key:
            raise UserError(_(
                'Chưa cấu hình OpenAI API Key.\n'
                'Vào Settings → Technical → System Parameters → tạo key "openai.api_key"'
            ))

        # Lấy cấu hình từ config model
        config = self._get_config()
        ai_model = config.ai_model or 'gpt-4o-mini'
        max_tokens = config.max_tokens or 2000
        temperature = config.temperature or 0.3
        system_prompt = config.system_prompt or 'Bạn là chuyên gia tư vấn giá bán sản phẩm.'

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
                    'max_tokens': max_tokens,
                    'temperature': temperature,
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
