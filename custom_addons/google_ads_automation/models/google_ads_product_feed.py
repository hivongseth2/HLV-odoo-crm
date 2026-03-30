from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup
from datetime import timedelta
import logging
import re

_logger = logging.getLogger(__name__)

def clean_str(s):
    if not s: return ""
    return re.sub(r'[^a-zA-Z0-9]', '', s).lower()


class GoogleAdsProductFeed(models.Model):
    _name = 'google.ads.product.feed'
    _description = 'Product Feed - Liên kết Sản phẩm & Google Ads'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Tên Feed', required=True, tracking=True)
    active = fields.Boolean(default=True, string='Kích Hoạt')
    account_id = fields.Many2one(
        'google.ads.account', string='Tài Khoản Google Ads',
        required=True, ondelete='restrict', tracking=True,
    )
    note = fields.Text(string='Ghi Chú')

    line_ids = fields.One2many(
        'google.ads.product.feed.line', 'feed_id',
        string='Danh Sách Sản Phẩm',
    )

    # -- Statistics --
    line_count = fields.Integer(
        string='Số Sản Phẩm', compute='_compute_line_count', store=True,
    )
    strategy_count = fields.Integer(
        string='Số Chiến Lược', compute='_compute_strategy_count',
    )

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def _compute_strategy_count(self):
        for rec in self:
            rec.strategy_count = self.env['google.ads.strategy'].search_count([
                ('feed_id', '=', rec.id),
            ])

    hero_header_html = fields.Html(compute='_compute_hero_header_html')

    def _compute_hero_header_html(self):
        for rec in self:
            active_ping = 'bg-success' if rec.active else 'bg-danger'
            
            # Inventory Status Distribution
            critical = len(rec.line_ids.filtered(lambda l: l.stock_status == 'critical'))
            low = len(rec.line_ids.filtered(lambda l: l.stock_status == 'low'))
            normal = len(rec.line_ids.filtered(lambda l: l.stock_status == 'normal'))
            
            total = rec.line_count or 1
            crit_p = (critical / total) * 100
            low_p = (low / total) * 100
            norm_p = (normal / total) * 100
            
            html = f"""
                <div class="o_hero_header">
                    <div class="status_badge">
                        <span class="o_status_ping {active_ping}"></span>
                        <span class="badge text-bg-light fw-bold shadow-sm border">{'ACTIVE' if rec.active else 'INACTIVE'}</span>
                    </div>
                    <div class="row align-items-center">
                        <div class="col-auto">
                            <div class="bg-light p-3 rounded-4 border text-warning">
                                <i class="fa fa-cubes fa-4x"></i>
                            </div>
                        </div>
                        <div class="col">
                            <span class="o_logic_tag mb-2 d-inline-block bg-warning text-dark">INVENTORY FEED</span>
                            
                            <p class="text-muted mt-2 mb-0 fw-medium">
                                <i class="fa fa-briefcase me-1"></i> Account: 
                                <span class="text-dark fw-bold">{rec.account_id.name or '—'}</span>
                            </p>
                        </div>
                        <div class="col-md-5">
                            <div class="o_visual_box">
                                <span class="o_visual_label">Inventory Distribution</span>
                                <div class="progress mb-2 mt-2" style="height: 12px;">
                                    <div class="progress-bar bg-danger" style="width: {crit_p}%" title="Critical: {critical}"></div>
                                    <div class="progress-bar bg-warning" style="width: {low_p}%" title="Low: {low}"></div>
                                    <div class="progress-bar bg-success" style="width: {norm_p}%" title="Normal: {normal}"></div>
                                </div>
                                <div class="d-flex justify-content-between text-muted mt-3" style="font-size: 11px;">
                                    <span><i class="fa fa-circle text-danger me-1"></i> Critical ({critical})</span>
                                    <span><i class="fa fa-circle text-warning me-1"></i> Low ({low})</span>
                                    <span><i class="fa fa-circle text-success me-1"></i> Healthy ({normal})</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            """
            rec.hero_header_html = Markup(html)

    # -----------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------
    def action_refresh_stock(self):
        """Cập nhật lại tồn kho & giá từ Odoo cho tất cả dòng trong feed"""
        self.ensure_one()
        for line in self.line_ids:
            line._compute_stock_fields()
            line._compute_margin_percent()
            line._compute_avg_daily_sales()
        self.message_post(body=_("Đã cập nhật tồn kho & giá cho %s sản phẩm.") % len(self.line_ids))
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đã Làm Mới Tồn Kho'),
                'message': _('Dữ liệu tồn kho và giá bán đã được cập nhật từ hệ thống Odoo.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_add_products_wizard(self):
        """Mở wizard để thêm sản phẩm vào feed"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Thêm Sản Phẩm Vào Feed'),
            'res_model': 'google.ads.product.feed.add.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_feed_id': self.id},
        }

    def action_view_strategies(self):
        """Mở danh sách chiến lược của Feed này"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Chiến Lược'),
            'res_model': 'google.ads.strategy',
            'view_mode': 'list,form',
            'domain': [('feed_id', '=', self.id)],
            'context': {'default_feed_id': self.id, 'default_account_id': self.account_id.id},
        }

    def action_auto_link_campaigns(self):
        """Tự động tìm và link Campaign nếu tên Campaign chứa Mã SP (SKU)"""
        self.ensure_one()
        count = 0
        campaigns = self.env['google.ads.campaign'].search([
            ('account_id', '=', self.account_id.id),
            ('status', 'in', ['enabled', 'paused', 'unknown'])
        ])
        
        if not campaigns:
            raise UserError(_("Không tìm thấy Chiến dịch nào khớp trong tài khoản '%s'. "
                              "Anh vui lòng nhấn 'Đồng bộ dữ liệu' ở Tài khoản Google Ads trước.") % self.account_id.name)

        for line in self.line_ids:
            sku = (line.product_default_code or '').strip()
            name = (line.product_id.name or '').strip()
            if not sku and not name:
                continue
            
            matched = self.env['google.ads.campaign'].browse()
            
            # 1. Match bằng SKU (Tìm trong tên Campaign - dùng clean_str để bỏ qua dấu gạch, khoảng trắng)
            if sku:
                c_sku = clean_str(sku)
                matched |= campaigns.filtered(lambda c: c_sku in clean_str(c.name))
            
            # 2. Match bằng Tên Sản phẩm (Nếu chưa có SKU match)
            if not matched and name:
                # Thử tìm tên sản phẩm trong tên campaign
                matched |= campaigns.filtered(lambda c: name.lower() in (c.name or '').lower())
                
            if matched:
                # Thêm vào Many2many (link) - trigger recompute of product_ids on campaign
                line.campaign_ids = [fields.Command.link(c.id) for c in matched]
                count += 1
        
        message = _('Đã tự động liên kết thành công cho %s sản phẩm.') % count
        title = _('Thành công')
        type = 'success'
        
        if count == 0:
            title = _('Thông báo')
            message = _('Không tìm thấy Chiến dịch nào khớp với SKU hoặc Tên sản phẩm trong Feed này. '
                        'Anh vui lòng kiểm tra lại tên Chiến dịch hoặc gán thủ công ở cột "Chiến Dịch Liên Kết".')
            type = 'warning'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': type,
                'sticky': count == 0,
            }
        }


class GoogleAdsProductFeedLine(models.Model):
    _name = 'google.ads.product.feed.line'
    _description = 'Dòng sản phẩm trong Product Feed'
    _order = 'product_id'

    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('product_id', 'product_id.name', 'product_default_code')
    def _compute_display_name(self):
        for line in self:
            line.display_name = f"[{line.product_default_code}] {line.product_id.name}" if line.product_default_code else line.product_id.name

    feed_id = fields.Many2one(
        'google.ads.product.feed', string='Feed',
        required=True, ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.template', string='Sản Phẩm', required=True,
        ondelete='cascade',
    )
    campaign_ids = fields.Many2many(
        'google.ads.campaign', 'google_ads_feed_line_campaign_rel',
        'feed_line_id', 'campaign_id',
        string='Chiến Dịch Liên Kết',
    )

    # -- Computed stock & price fields (from Odoo) --
    product_default_code = fields.Char(
        related='product_id.default_code', string='Mã SP', store=True, readonly=True
    )
    qty_available = fields.Float(
        string='Tồn Kho Thực Tế', compute='_compute_stock_fields', store=True, readonly=True
    )
    virtual_available = fields.Float(
        string='Tồn Kho Dự Kiến', compute='_compute_stock_fields', store=True, readonly=True
    )
    sale_price = fields.Float(
        string='Giá Bán', compute='_compute_stock_fields', store=True, readonly=True
    )
    cost_price = fields.Float(
        string='Giá Vốn', compute='_compute_stock_fields', store=True, readonly=True
    )
    margin_percent = fields.Float(
        string='Biên LN (%)', compute='_compute_margin_percent', store=True, readonly=True,
        help='(Giá Bán - Giá Vốn) / Giá Bán × 100',
    )
    avg_daily_sales = fields.Float(
        string='TB Bán/Ngày (30d)', compute='_compute_avg_daily_sales', store=True, readonly=True,
        help='Số lượng bán trung bình mỗi ngày trong 30 ngày gần nhất',
    )
    days_of_stock = fields.Float(
        string='Số Ngày Tồn', compute='_compute_days_of_stock', store=True, readonly=True,
        help='Tồn kho / TB bán mỗi ngày → bao nhiêu ngày nữa thì hết hàng',
    )

    # -- Status badge for quick glance --
    stock_status = fields.Selection([
        ('critical', 'Sắp Hết Hàng'),
        ('low',      'Tồn Thấp'),
        ('normal',   'Bình Thường'),
        ('high',     'Tồn Cao'),
    ], string='Trạng Thái Tồn', compute='_compute_stock_status', store=True, readonly=True)

    @api.depends('product_id', 'product_id.qty_available',
                 'product_id.virtual_available', 'product_id.list_price',
                 'product_id.standard_price')
    def _compute_stock_fields(self):
        for line in self:
            prod = line.product_id
            if prod:
                line.qty_available = prod.qty_available
                line.virtual_available = prod.virtual_available
                line.sale_price = prod.list_price
                line.cost_price = prod.standard_price
            else:
                line.qty_available = 0
                line.virtual_available = 0
                line.sale_price = 0
                line.cost_price = 0

    @api.depends('sale_price', 'cost_price')
    def _compute_margin_percent(self):
        for line in self:
            if line.sale_price > 0:
                line.margin_percent = (line.sale_price - line.cost_price) / line.sale_price * 100
            else:
                line.margin_percent = 0

    @api.depends('product_id')
    def _compute_avg_daily_sales(self):
        """Tính TB bán/ngày dựa trên sale.order.line 30 ngày gần nhất"""
        date_from = fields.Date.today() - timedelta(days=30)
        for line in self:
            if not line.product_id:
                line.avg_daily_sales = 0
                continue
            # Lấy tổng qty_delivered từ SO lines (theo rule 9.1)
            sol_domain = [
                ('product_id.product_tmpl_id', '=', line.product_id.id),
                ('order_id.state', 'in', ['sale', 'done']),
                ('order_id.date_order', '>=', date_from),
            ]
            sols = self.env['sale.order.line'].search(sol_domain)
            total_delivered = sum(sols.mapped('qty_delivered'))
            line.avg_daily_sales = total_delivered / 30.0

    @api.depends('qty_available', 'avg_daily_sales')
    def _compute_days_of_stock(self):
        for line in self:
            if line.avg_daily_sales > 0:
                line.days_of_stock = line.qty_available / line.avg_daily_sales
            else:
                line.days_of_stock = 9999  # Không bán → tồn vô hạn

    @api.depends('qty_available', 'days_of_stock')
    def _compute_stock_status(self):
        for line in self:
            if line.qty_available <= 0:
                line.stock_status = 'critical'
            elif line.days_of_stock < 7:
                line.stock_status = 'critical'
            elif line.days_of_stock < 30:
                line.stock_status = 'low'
            elif line.days_of_stock > 90:
                line.stock_status = 'high'
            else:
                line.stock_status = 'normal'
    def write(self, vals):
        # Product-Campaign linking is now handled by computed field on Campaign.
        # No manual sync needed here.
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)
