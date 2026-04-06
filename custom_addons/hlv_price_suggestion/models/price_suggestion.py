import json
import logging
from datetime import timedelta

import requests

from odoo import api, fields, models
from odoo.tools.translate import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PriceSuggestion(models.Model):
    _name = 'price.suggestion'
    _description = 'Đề xuất giá bán sản phẩm'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'suggestion_date desc, id desc'
    _rec_name = 'product_id'

    # ── Core fields ──
    product_id = fields.Many2one(
        'product.product', string='Sản phẩm', required=True,
        tracking=True, index=True,
    )
    product_tmpl_id = fields.Many2one(
        'product.template', string='Mẫu sản phẩm',
        related='product_id.product_tmpl_id', store=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Công ty',
        default=lambda self: self.env.company, required=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Tiền tệ',
        related='company_id.currency_id', store=True,
    )
    suggestion_date = fields.Datetime(
        string='Ngày đề xuất', default=fields.Datetime.now,
        tracking=True,
    )

    # ── Price data ──
    last_purchase_price = fields.Float(
        string='Giá nhập gần nhất', digits='Product Price',
        help='Giá nhập từ đơn mua hàng gần nhất',
    )
    avg_purchase_price = fields.Float(
        string='Giá nhập trung bình', digits='Product Price',
        help='Giá nhập trung bình từ các đơn mua hàng',
    )
    current_sale_price = fields.Float(
        string='Giá bán hiện tại', digits='Product Price',
        help='Giá bán hiện tại trên sản phẩm (list price)',
    )
    suggested_price = fields.Float(
        string='Giá đề xuất', digits='Product Price',
        tracking=True,
        help='Giá bán được đề xuất bởi hệ thống / AI',
    )

    # ── Stock & Sales metrics ──
    stock_qty = fields.Float(
        string='Số lượng tồn kho',
        help='Số lượng tồn kho hiện tại (qty_available)',
    )
    avg_daily_sales = fields.Float(
        string='Trung bình bán/ngày',
        digits=(16, 2),
        help='Số lượng trung bình bán mỗi ngày (30 ngày gần nhất)',
    )
    total_sold_30d = fields.Float(
        string='Đã bán (30 ngày)',
        help='Tổng số lượng đã bán trong 30 ngày gần nhất',
    )
    days_of_stock = fields.Float(
        string='Số ngày tồn kho còn',
        compute='_compute_days_of_stock', store=True,
        help='Ước tính số ngày tồn kho còn đủ bán',
    )
    sales_rank = fields.Selection([
        ('hot', 'Bán chạy'),
        ('normal', 'Bình thường'),
        ('slow', 'Bán chậm'),
        ('no_sale', 'Không bán'),
    ], string='Xếp hạng bán hàng', compute='_compute_sales_rank', store=True)

    supplier_stock_status = fields.Selection([
        ('available', 'Hãng còn hàng'),
        ('low', 'Hãng sắp hết'),
        ('out_of_stock', 'Hãng hết hàng'),
        ('unknown', 'Không rõ'),
    ], string='Tình trạng hàng NCC', default='unknown',
       tracking=True,
       help='Tình trạng hàng từ nhà cung cấp (hãng)',
    )

    # ── AI analysis ──
    ai_analysis = fields.Text(
        string='Phân tích AI',
        help='Phân tích và lý do đề xuất giá từ AI',
    )
    ai_model_used = fields.Char(string='AI Model')

    # ── Computed ──
    price_change_pct = fields.Float(
        string='% Thay đổi giá',
        compute='_compute_price_change', store=True,
        help='Phần trăm thay đổi so với giá bán hiện tại',
    )
    margin_pct = fields.Float(
        string='% Biên lợi nhuận',
        compute='_compute_margin', store=True,
        help='Biên lợi nhuận dựa trên giá nhập gần nhất',
    )

    # ── State ──
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('suggested', 'Đã đề xuất'),
        ('approved', 'Đã duyệt'),
        ('applied', 'Đã áp dụng'),
        ('rejected', 'Từ chối'),
    ], string='Trạng thái', default='draft', tracking=True, required=True)

    note = fields.Text(string='Ghi chú')

    # ── Computes ──
    @api.depends('stock_qty', 'avg_daily_sales')
    def _compute_days_of_stock(self):
        for rec in self:
            if rec.avg_daily_sales > 0:
                rec.days_of_stock = rec.stock_qty / rec.avg_daily_sales
            else:
                rec.days_of_stock = 9999.0 if rec.stock_qty > 0 else 0.0

    @api.depends('avg_daily_sales', 'total_sold_30d')
    def _compute_sales_rank(self):
        for rec in self:
            daily = rec.avg_daily_sales
            if daily <= 0:
                rec.sales_rank = 'no_sale'
            elif daily < 1:
                rec.sales_rank = 'slow'
            elif daily < 5:
                rec.sales_rank = 'normal'
            else:
                rec.sales_rank = 'hot'

    @api.depends('suggested_price', 'current_sale_price')
    def _compute_price_change(self):
        for rec in self:
            if rec.current_sale_price > 0 and rec.suggested_price > 0:
                rec.price_change_pct = (
                    (rec.suggested_price - rec.current_sale_price)
                    / rec.current_sale_price * 100
                )
            else:
                rec.price_change_pct = 0.0

    @api.depends('suggested_price', 'last_purchase_price')
    def _compute_margin(self):
        for rec in self:
            if rec.suggested_price > 0 and rec.last_purchase_price > 0:
                rec.margin_pct = (
                    (rec.suggested_price - rec.last_purchase_price)
                    / rec.suggested_price * 100
                )
            else:
                rec.margin_pct = 0.0

    # ── Actions ──
    def action_collect_data(self):
        """Thu thập dữ liệu giá nhập, tồn kho, lượt bán cho sản phẩm."""
        for rec in self:
            rec._collect_purchase_data()
            rec._collect_stock_data()
            rec._collect_sales_data()

    def action_suggest_price_rule(self):
        """Đề xuất giá dựa trên quy tắc (không cần AI)."""
        for rec in self:
            rec._collect_purchase_data()
            rec._collect_stock_data()
            rec._collect_sales_data()
            rec._calculate_suggested_price_rule()
            rec.state = 'suggested'

    def action_suggest_price_ai(self):
        """Đề xuất giá bằng AI (OpenAI)."""
        for rec in self:
            rec._collect_purchase_data()
            rec._collect_stock_data()
            rec._collect_sales_data()
            rec._calculate_suggested_price_ai()
            rec.state = 'suggested'

    def action_approve(self):
        """Duyệt đề xuất giá."""
        self.filtered(lambda r: r.state == 'suggested').write({
            'state': 'approved',
        })

    def action_apply_price(self):
        """Áp dụng giá đề xuất lên sản phẩm."""
        for rec in self:
            rec.ensure_one()
            if rec.state != 'approved':
                raise UserError(_('Chỉ có thể áp dụng giá đã được duyệt.'))
            if rec.suggested_price <= 0:
                raise UserError(_('Giá đề xuất phải lớn hơn 0.'))
            rec.product_id.product_tmpl_id.write({
                'list_price': rec.suggested_price,
            })
            rec.state = 'applied'
            rec.message_post(
                body=_(
                    'Đã áp dụng giá đề xuất %(price)s lên sản phẩm %(product)s',
                    price=rec.suggested_price,
                    product=rec.product_id.display_name,
                ),
            )

    def action_reject(self):
        """Từ chối đề xuất giá."""
        self.filtered(lambda r: r.state in ('suggested', 'approved')).write({
            'state': 'rejected',
        })

    def action_reset_draft(self):
        """Đưa về nháp."""
        self.write({'state': 'draft'})

    # ── Batch generation ──
    def action_batch_generate(self):
        """Tạo đề xuất giá cho tất cả sản phẩm có hàng tồn hoặc bán gần đây."""
        products = self.env['product.product'].search([
            ('type', '=', 'product'),
            ('active', '=', True),
        ])
        created = self.env['price.suggestion']
        for product in products:
            # Bỏ qua sản phẩm đã có đề xuất đang chờ  duyệt
            existing = self.search([
                ('product_id', '=', product.id),
                ('company_id', '=', self.env.company.id),
                ('state', 'in', ('draft', 'suggested', 'approved')),
            ], limit=1)
            if existing:
                continue
            suggestion = self.create({
                'product_id': product.id,
                'company_id': self.env.company.id,
            })
            suggestion.action_suggest_price_rule()
            created |= suggestion
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Tạo đề xuất giá'),
                'message': _('Đã tạo %d đề xuất giá mới.') % len(created),
                'type': 'success',
                'sticky': False,
            },
        }

    # ── Data Collection ──
    def _collect_purchase_data(self):
        """Lấy giá nhập từ đơn mua hàng."""
        self.ensure_one()
        POLine = self.env['purchase.order.line']

        # Giá nhập gần nhất
        last_po_line = POLine.search([
            ('product_id', '=', self.product_id.id),
            ('order_id.state', 'in', ('purchase', 'done')),
            ('company_id', '=', self.company_id.id),
        ], order='create_date desc', limit=1)

        if last_po_line:
            self.last_purchase_price = last_po_line.price_unit

        # Giá nhập trung bình (từ các PO confirmed, lấy 10 gần nhất)
        recent_po_lines = POLine.search([
            ('product_id', '=', self.product_id.id),
            ('order_id.state', 'in', ('purchase', 'done')),
            ('company_id', '=', self.company_id.id),
        ], order='create_date desc', limit=10)

        if recent_po_lines:
            total_cost = sum(l.price_unit * l.product_qty for l in recent_po_lines)
            total_qty = sum(l.product_qty for l in recent_po_lines)
            self.avg_purchase_price = total_cost / total_qty if total_qty else 0.0
        else:
            self.avg_purchase_price = 0.0

        # Giá bán hiện tại
        self.current_sale_price = self.product_id.lst_price or 0.0

    def _collect_stock_data(self):
        """Lấy thông tin tồn kho."""
        self.ensure_one()
        self.stock_qty = self.product_id.with_company(self.company_id).qty_available

    def _collect_sales_data(self):
        """Lấy dữ liệu bán hàng 30 ngày gần nhất."""
        self.ensure_one()
        date_from = fields.Datetime.now() - timedelta(days=30)

        sol_data = self.env['sale.order.line'].search([
            ('product_id', '=', self.product_id.id),
            ('order_id.state', 'in', ('sale', 'done')),
            ('order_id.date_order', '>=', date_from),
            ('order_id.company_id', '=', self.company_id.id),
        ])

        total_sold = sum(line.qty_delivered for line in sol_data)
        self.total_sold_30d = total_sold
        self.avg_daily_sales = total_sold / 30.0

    # ── Rule-based price calculation ──
    def _calculate_suggested_price_rule(self):
        """Tính giá đề xuất dựa trên các quy tắc kinh doanh."""
        self.ensure_one()

        base_price = self.last_purchase_price or self.avg_purchase_price
        if base_price <= 0:
            # Không có dữ liệu giá nhập → giữ giá hiện tại
            self.suggested_price = self.current_sale_price
            self.ai_analysis = _('Không có dữ liệu giá nhập. Giữ giá hiện tại.')
            return

        # Biên lợi nhuận mặc định 30%
        margin = 0.30
        reasons = []

        # ── Quy tắc 1: Bán chạy + tồn kho ít → tăng giá
        if self.sales_rank == 'hot' and self.days_of_stock < 15:
            margin += 0.15
            reasons.append('Bán chạy + tồn kho thấp → +15% margin')
        elif self.sales_rank == 'hot':
            margin += 0.05
            reasons.append('Sản phẩm bán chạy → +5% margin')

        # ── Quy tắc 2: Tồn kho rất ít (< 7 ngày) → tăng giá
        if 0 < self.days_of_stock < 7:
            margin += 0.10
            reasons.append('Tồn kho dưới 7 ngày → +10% margin')

        # ── Quy tắc 3: Hãng hết hàng → tăng giá mạnh
        if self.supplier_stock_status == 'out_of_stock':
            margin += 0.20
            reasons.append('Nhà cung cấp hết hàng → +20% margin')
        elif self.supplier_stock_status == 'low':
            margin += 0.10
            reasons.append('Nhà cung cấp sắp hết hàng → +10% margin')

        # ── Quy tắc 4: Bán chậm + tồn kho nhiều → giảm giá
        if self.sales_rank in ('slow', 'no_sale') and self.days_of_stock > 90:
            margin -= 0.10
            reasons.append('Bán chậm + tồn kho nhiều → -10% margin')

        # ── Quy tắc 5: Đảm bảo margin tối thiểu
        margin = max(margin, 0.10)

        suggested = base_price * (1 + margin)

        # Làm tròn lên hàng nghìn
        suggested = round(suggested / 1000) * 1000

        self.suggested_price = suggested
        self.ai_analysis = '\n'.join([
            _('=== Phân tích quy tắc ==='),
            _('Giá nhập cơ sở: %s') % f'{base_price:,.0f}',
            _('Margin áp dụng: %s%%') % f'{margin * 100:.0f}',
            '',
        ] + reasons + [
            '',
            _('Giá đề xuất: %s') % f'{suggested:,.0f}',
        ])

    # ── AI-based price calculation ──
    def _calculate_suggested_price_ai(self):
        """Gọi OpenAI API để đề xuất giá."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        api_key = ICP.get_param('openai.api_key')

        if not api_key:
            raise UserError(_(
                'Chưa cấu hình OpenAI API Key.\n'
                'Vào Settings → System Parameters → tạo key "openai.api_key"'
            ))

        ai_model = ICP.get_param('openai.model', 'gpt-4o-mini')

        # Chuẩn bị dữ liệu context cho AI
        product_info = {
            'ten_san_pham': self.product_id.display_name,
            'ma_san_pham': self.product_id.default_code or '',
            'gia_nhap_gan_nhat': self.last_purchase_price,
            'gia_nhap_trung_binh': self.avg_purchase_price,
            'gia_ban_hien_tai': self.current_sale_price,
            'ton_kho': self.stock_qty,
            'ban_trung_binh_ngay': self.avg_daily_sales,
            'tong_ban_30_ngay': self.total_sold_30d,
            'so_ngay_ton_kho_con': self.days_of_stock,
            'xep_hang_ban': dict(
                self._fields['sales_rank'].selection
            ).get(self.sales_rank, ''),
            'tinh_trang_hang_ncc': dict(
                self._fields['supplier_stock_status'].selection
            ).get(self.supplier_stock_status, 'Không rõ'),
        }

        # Lấy giá bán của các công ty khác (cùng sản phẩm template)
        other_prices = []
        other_suggestions = self.search([
            ('product_tmpl_id', '=', self.product_tmpl_id.id),
            ('company_id', '!=', self.company_id.id),
            ('state', 'in', ('approved', 'applied')),
        ], order='suggestion_date desc')
        for s in other_suggestions[:5]:
            other_prices.append({
                'cong_ty': s.company_id.name,
                'gia_de_xuat': s.suggested_price,
                'ngay': str(s.suggestion_date),
            })

        system_prompt = """Bạn là chuyên gia định giá sản phẩm cho doanh nghiệp bán lẻ tại Việt Nam.
Nhiệm vụ: Phân tích dữ liệu và đề xuất giá bán tối ưu.

QUY TẮC ĐỊNH GIÁ:
1. Giá đề xuất PHẢI cao hơn giá nhập (đảm bảo lợi nhuận tối thiểu 10%)
2. Sản phẩm bán chạy + tồn kho ít → tăng giá (market demand cao)
3. Nhà cung cấp hết hàng → tăng giá (scarcity pricing)
4. Sản phẩm bán chậm + tồn nhiều → giảm giá để xả hàng
5. So sánh với giá bán các công ty khác để đảm bảo cạnh tranh
6. Giá đề xuất nên làm tròn hàng nghìn (VND)

Trả về JSON format:
{
    "suggested_price": <số>,
    "margin_percent": <số>,
    "confidence": "high|medium|low",
    "reasons": ["lý do 1", "lý do 2", ...],
    "summary": "Tóm tắt phân tích ngắn gọn"
}
Chỉ trả về JSON, không thêm text khác."""

        user_prompt = f"""Dữ liệu sản phẩm:
{json.dumps(product_info, ensure_ascii=False, indent=2)}

Giá bán tại công ty khác:
{json.dumps(other_prices, ensure_ascii=False, indent=2) if other_prices else 'Không có dữ liệu'}

Hãy đề xuất giá bán tối ưu cho công ty "{self.company_id.name}"."""

        try:
            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': ai_model,
                    'messages': [
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': user_prompt},
                    ],
                    'max_tokens': 1000,
                    'temperature': 0.3,
                },
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            ai_content = result['choices'][0]['message']['content']

            # Parse JSON response
            # Loại bỏ markdown code block nếu có
            cleaned = ai_content.strip()
            if cleaned.startswith('```'):
                cleaned = cleaned.split('\n', 1)[-1]
                if cleaned.endswith('```'):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()

            ai_data = json.loads(cleaned)

            self.suggested_price = float(ai_data.get('suggested_price', 0))
            self.ai_model_used = ai_model

            reasons = ai_data.get('reasons', [])
            summary = ai_data.get('summary', '')
            confidence = ai_data.get('confidence', '')

            analysis_parts = [
                _('=== Phân tích AI (%s) ===') % ai_model,
                '',
                _('Độ tin cậy: %s') % confidence,
                _('Giá đề xuất: %s') % f"{self.suggested_price:,.0f}",
                _('Biên LN: %s%%') % ai_data.get('margin_percent', ''),
                '',
                _('Lý do:'),
            ]
            for i, reason in enumerate(reasons, 1):
                analysis_parts.append(f'  {i}. {reason}')
            analysis_parts.extend(['', _('Tóm tắt: %s') % summary])

            self.ai_analysis = '\n'.join(analysis_parts)

        except requests.exceptions.Timeout:
            raise UserError(_('Kết nối OpenAI bị timeout. Vui lòng thử lại.'))
        except requests.exceptions.RequestException as e:
            raise UserError(_('Lỗi kết nối OpenAI: %s') % str(e))
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            _logger.error('AI response parse error: %s | content: %s', e, ai_content)
            raise UserError(_(
                'Không thể phân tích phản hồi từ AI.\nNội dung: %s'
            ) % ai_content)

    # ── Cron ──
    @api.model
    def _cron_generate_suggestions(self):
        """Cron job: Tự động tạo đề xuất giá cho sản phẩm bán chạy."""
        companies = self.env['res.company'].search([])
        for company in companies:
            self_company = self.with_company(company)

            # Lấy sản phẩm có bán trong 30 ngày gần nhất
            date_from = fields.Datetime.now() - timedelta(days=30)
            sol_data = self.env['sale.order.line'].sudo().search([
                ('order_id.state', 'in', ('sale', 'done')),
                ('order_id.date_order', '>=', date_from),
                ('order_id.company_id', '=', company.id),
                ('product_id.type', '=', 'product'),
            ])
            product_ids = sol_data.mapped('product_id').ids

            for pid in product_ids:
                # Bỏ qua nếu đã có đề xuất pending
                existing = self_company.sudo().search([
                    ('product_id', '=', pid),
                    ('company_id', '=', company.id),
                    ('state', 'in', ('draft', 'suggested', 'approved')),
                ], limit=1)
                if existing:
                    continue

                try:
                    suggestion = self_company.sudo().create({
                        'product_id': pid,
                        'company_id': company.id,
                    })
                    suggestion.action_suggest_price_rule()
                except Exception as e:
                    _logger.warning(
                        'Lỗi tạo đề xuất giá cho product %s: %s', pid, e
                    )
