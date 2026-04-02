from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)

class GoogleAdsCampaign(models.Model):
    _name = 'google.ads.campaign'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Chiến dịch Google Ads'

    name = fields.Char(string='Tên Chiến Dịch', required=True)
    account_id = fields.Many2one('google.ads.account', string='Tài Khoản Google Ads', required=True, ondelete='cascade')
    
    hero_header_html = fields.Html(compute='_compute_hero_header_html')
    performance_dashboard_html = fields.Html(compute='_compute_performance_dashboard_html')
    google_campaign_id = fields.Char(string='Google Campaign ID', index=True, readonly=True)
    state = fields.Selection([
        ('draft', 'Nháp (Local)'),
        ('synced', 'Đã đồng bộ Google'),
    ], string='Trạng thái bộ máy', default='draft', required=True, tracking=True)
    product_feed_id = fields.Many2one(
        'google.ads.product.feed', string='Nguồn Cấp SP (Feed)',
        ondelete='set null', help='Chọn một Feed để tự động lấy tất cả sản phẩm'
    )
    feed_line_ids = fields.Many2many(
        'google.ads.product.feed.line', 'google_ads_feed_line_campaign_rel',
        'campaign_id', 'feed_line_id',
        string='Dòng Feed Liên Kết',
    )
    product_ids = fields.Many2many(
        'product.template', string='Sản Phẩm', 
        compute='_compute_product_ids', store=True,
        help='Các sản phẩm được quảng cáo trong chiến dịch này (tự động lấy từ Product Feed)'
    )

    # ── Adsroid Integration ──────────────────────
    adsroid_last_insight = fields.Html(string='Nhận định AI (Adsroid)', readonly=True)
    adsroid_log_ids = fields.One2many(
        'google.ads.adsroid.log', 'campaign_id', 
        string='Lịch sử Adsroid', readonly=True
    )

    @api.onchange('product_feed_id')
    def _onchange_product_feed_id(self):
        """Tự động điền các sản phẩm từ Feed đã chọn"""
        if self.product_feed_id:
            # Lấy tất cả dòng từ Feed mới chọn
            lines = self.product_feed_id.line_ids
            if lines:
                # Command.set (6, 0, [ids]) trong Odoo 18
                self.feed_line_ids = [fields.Command.set(lines.ids)]
            else:
                self.feed_line_ids = [fields.Command.clear()]

    @api.depends('feed_line_ids.product_id')
    def _compute_product_ids(self):
        for rec in self:
            rec.product_ids = rec.feed_line_ids.mapped('product_id')

    def _compute_hero_header_html(self):
        for rec in self:
            status_color = 'bg-success' if rec.status == 'enabled' else 'bg-warning' if rec.status == 'paused' else 'bg-danger'
            cr_width = min(rec.conversion_rate * 5, 100) if rec.conversion_rate > 0 else 0
            roas_width = min(rec.roas * 20, 100) if rec.roas > 0 else 0
            
            html = f"""
                <div class="o_hero_header">
                    <div class="status_badge">
                        <span class="o_status_ping {status_color}"></span>
                        <span class="badge text-bg-light fw-bold shadow-sm border">{dict(self._fields['status'].selection).get(rec.status, rec.status)}</span>
                    </div>
                    <div class="row align-items-center">
                        <div class="col-auto">
                            <div class="bg-light p-3 rounded-4 border text-primary">
                                <i class="fa fa-bullhorn fa-4x"></i>
                            </div>
                        </div>
                        <div class="col">
                            <span class="o_logic_tag mb-2 d-inline-block bg-primary">GOOGLE CAMPAIGN ENGINE</span>
                            <div class="d-flex align-items-center text-muted mt-2 mb-0 fw-medium">
                                <div>
                                    <i class="fa fa-university me-1"></i> Account: <span class="text-dark">{rec.account_id.name or '—'}</span>
                                </div>
                                <div class="ms-4">
                                    <i class="fa fa-info-circle me-1"></i> Channel: <span class="text-dark">{rec.channel_type}</span>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="o_visual_box">
                                <span class="o_visual_label mb-3">Campaign Success Probability</span>
                                <div class="mb-3">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Conversion Ratio</span>
                                        <span class="o_metric_value text-warning">{rec.conversion_rate:.2f}%</span>
                                    </div>
                                    <div class="progress mt-1" style="height: 6px;">
                                        <div class="progress-bar bg-warning" style="width: {cr_width}%"></div>
                                    </div>
                                </div>
                                <div class="mb-0">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Portfolio ROAS</span>
                                        <span class="o_metric_value text-info">{rec.roas:.1f}x</span>
                                    </div>
                                    <div class="progress mt-1" style="height: 6px;">
                                        <div class="progress-bar bg-info" style="width: {roas_width}%"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            """
            rec.hero_header_html = Markup(html)

    def _compute_performance_dashboard_html(self):
        for rec in self:
            html = f"""
                <div class="row g-4 mt-2">
                    <div class="col-md-3">
                        <div class="o_premium_metric_card">
                            <div class="o_metric_label">Clicks</div>
                            <div class="o_metric_value">{rec.clicks:,}</div>
                            <div class="o_metric_sub_label text-primary"><i class="fa fa-mouse-pointer me-1"></i>Total Interaction</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="o_premium_metric_card">
                            <div class="o_metric_label">Impressions</div>
                            <div class="o_metric_value">{rec.impressions:,}</div>
                            <div class="o_metric_sub_label text-info"><i class="fa fa-eye me-1"></i>Total Visibility</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="o_premium_metric_card">
                            <div class="o_metric_label">Conversions</div>
                            <div class="o_metric_value">{rec.conversions:.1f}</div>
                            <div class="o_metric_sub_label text-success"><i class="fa fa-shopping-cart me-1"></i>Total Orders</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="o_premium_metric_card">
                            <div class="o_metric_label">Cost</div>
                            <div class="o_metric_value" style="font-size: 1.3rem;">{rec.cost:,.0f} VNĐ</div>
                            <div class="o_metric_sub_label text-danger"><i class="fa fa-bank me-1"></i>Total Investment</div>
                        </div>
                    </div>
                </div>
            """
            rec.performance_dashboard_html = Markup(html)


    status = fields.Selection([
        ('unspecified', 'Chưa xác định'),
        ('unknown', 'Không rõ'),
        ('enabled', 'Đang hoạt động'),
        ('paused', 'Tạm dừng'),
        ('removed', 'Đã xóa'),
    ], string='Trạng Thái', default='unknown', readonly=True)

    channel_type = fields.Selection([
        ('SEARCH',          'Tìm Kiếm (Search)'),
        ('DISPLAY',         'Hiển Thị (Display)'),
        ('SHOPPING',        'Mua Sắm (Shopping)'),
        ('VIDEO',           'Video (YouTube)'),
        ('MULTI_CHANNEL',   'Đa Kênh (UAC/App)'),
        ('SMART',           'Thông Minh (Smart)'),
        ('PERFORMANCE_MAX', 'Tối Đa Hiệu Suất (PMax)'),
        ('DISCOVERY',       'Khám Phá (Discovery)'),
        ('HOTEL',           'Khách Sạn (Hotel)'),
    ], string='Loại Kênh', help='Loại kênh quảng cáo từ Google Ads', readonly=True, default='SEARCH')

    is_dsa = fields.Boolean(string='Chiến dịch Tìm kiếm Động (DSA)', help='Bật nếu chiến dịch này đã được cấu hình DSA trên Google Ads.')

    video_sub_type = fields.Selection([
        ('VIDEO_ACTION', 'Video hành động (Video Action)'),
        ('VIDEO_NON_SKIPPABLE', 'Video không thể bỏ qua (Non-skippable)'),
        ('VIDEO_OUTSTREAM', 'Video ngoài luồng (Outstream)'),
        ('VIDEO_SEQUENCE', 'Luồng video nối tiếp (Sequence)'),
    ], string='Cấu Hình Video', help='Loại hình phụ chuyên sâu cho kênh Video')

    app_sub_type = fields.Selection([
        ('APP_CAMPAIGN', 'Cài đặt ứng dụng (App Install)'),
        ('APP_CAMPAIGN_FOR_ENGAGEMENT', 'Tương tác ứng dụng (App Engagement)'),
        ('APP_CAMPAIGN_FOR_PRE_REGISTRATION', 'Đăng ký trước (App Pre-reg)'),
    ], string='Cấu Hình Ứng Dụng', help='Loại hình phụ chuyên sâu cho kênh Đa Kênh (App)')

    # Cấu hình Ứng dụng (Cho loại MULTI_CHANNEL)
    app_id = fields.Char(string='ID Ứng dụng', help='Ví dụ: com.myapp.android cho Play Store hoặc số ID cho App Store', tracking=True)
    app_store = fields.Selection([
        ('GOOGLE_APP_STORE', 'Google Play Store'),
        ('APPLE_APP_STORE', 'Apple App Store'),
    ], string='Cửa hàng', default='GOOGLE_APP_STORE', tracking=True)
    app_bidding_goal = fields.Selection([
        ('OPTIMIZE_INSTALLS_TARGET_INSTALL_COST', 'Tối ưu lượt cài đặt (Target CPA)'),
        ('OPTIMIZE_IN_APP_CONVERSIONS_TARGET_INSTALL_COST', 'Tối ưu hành động trong ứng dụng'),
        ('OPTIMIZE_IN_APP_CONVERSIONS_TARGET_CONVERSION_COST', 'Tối ưu chuyển đổi trong ứng dụng'),
        ('OPTIMIZE_RETURN_ON_AD_SPEND', 'Tối ưu ROAS'),
    ], string='Mục tiêu thầu App', default='OPTIMIZE_INSTALLS_TARGET_INSTALL_COST', tracking=True)

    # Cấu hình Chiến dịch (Dùng để tạo mới/cập nhật)
    budget_amount = fields.Float(string='Ngân sách hàng ngày', default=50000.0, tracking=True)
    business_name = fields.Char(string='Tên thương hiệu', help='Yêu cầu cho PMax nếu bật Brand Guidelines', tracking=True)
    logo_image = fields.Binary(string='Logo hình vuông', help='Yêu cầu cho PMax (tỷ lệ 1:1)')
    marketing_image = fields.Binary(string='Ảnh quảng cáo (Ngang)', help='Yêu cầu cho PMax (tỷ lệ 1.91:1 - Landscape)')
    final_url = fields.Char(string='URL trang đích (Landing Page)', help='URL trang web mà quảng cáo sẽ dẫn người dùng đến', tracking=True)

    # Thành phần quảng cáo PMax (Asset Group)
    # Tiêu đề (Headlines) - Max 30 chars
    pmax_headline_1 = fields.Char(string='Tiêu đề 1', help='Tối đa 30 ký tự', size=30)
    pmax_headline_2 = fields.Char(string='Tiêu đề 2', help='Tối đa 30 ký tự', size=30)
    pmax_headline_3 = fields.Char(string='Tiêu đề 3', help='Tối đa 30 ký tự', size=30)
    
    # Tiêu đề dài (Long Headline) - Max 90 chars
    pmax_long_headline = fields.Char(string='Tiêu đề dài', help='Tối đa 90 ký tự', size=90)
    
    # Mô tả (Descriptions) - Max 90 chars
    pmax_description_1 = fields.Char(string='Mô tả 1', help='Tối đa 90 ký tự', size=90)
    pmax_description_2 = fields.Char(string='Mô tả 2', help='Tối đa 90 ký tự', size=90)

    # Metrics (Chỉ số hiệu suất cơ bản)
    clicks = fields.Integer(string='Lượt Nhấp', default=0, readonly=True)
    impressions = fields.Integer(string='Lượt Hiển Thị', default=0, readonly=True)
    cost = fields.Float(string='Chi Phí', default=0.0, readonly=True)
    conversions = fields.Float(string='Lượt Chuyển Đổi', default=0.0, readonly=True)

    # Computed Metrics for UI
    conversion_rate = fields.Float(
        string='Tỷ Lệ Chuyển Đổi (%)', 
        compute='_compute_performance_metrics', store=False
    )
    roas = fields.Float(
        string='ROAS', 
        compute='_compute_performance_metrics', store=False,
        help='Doanh thu / Chi phí. Lưu ý: Cần module tính doanh thu thực tế để chính xác, mặc định lấy Conversions * 500k / Cost'
    )
    
    @api.depends('clicks', 'conversions', 'cost')
    def _compute_performance_metrics(self):
        for rec in self:
            # Conversion Rate
            if rec.clicks > 0:
                rec.conversion_rate = (rec.conversions / rec.clicks) * 100
            else:
                rec.conversion_rate = 0.0
                
            # ROAS (Giả lập doanh thu trung bình 500k/đơn hàng nếu chưa link thực tế)
            # Nếu có link thực tế từ google_ads_conversion thì lấy sum doanh thu
            if rec.cost > 0:
                # Tìm doanh thu thực tế từ Conversion model
                conversions = self.env['google.ads.conversion'].search([('campaign_id', '=', rec.id)])
                if conversions:
                    total_revenue = sum(c.revenue for c in conversions)
                    rec.roas = total_revenue / rec.cost
                else:
                    # Giả định doanh thu 500k cho demo
                    rec.roas = (rec.conversions * 500000) / rec.cost
            else:
                rec.roas = 0.0

    status_label = fields.Char(compute='_compute_status_label')

    @api.depends('status')
    def _compute_status_label(self):
        selection = dict(self._fields['status'].selection)
        for rec in self:
            rec.status_label = selection.get(rec.status, rec.status)

    hero_header_html = fields.Html(compute='_compute_hero_header_html')

    def _compute_hero_header_html(self):
        for rec in self:
            status_color = 'bg-success' if rec.status == 'enabled' else 'bg-warning' if rec.status == 'paused' else 'bg-danger'
            
            # Visualization logic for Premium looking charts
            roas_width = min(rec.roas * 20, 100) if rec.roas > 0 else 0 # 1.0 = 20%, 5.0 = 100%
            cr_width = min(rec.conversion_rate * 5, 100) if rec.conversion_rate > 0 else 0 # 20% CR = 100% width
            
            html = f"""
                <div class="o_hero_header">
                    <div class="status_badge">
                        <span class="o_status_ping {status_color}"></span>
                        <span class="badge text-bg-light fw-bold shadow-sm border">{rec.status_label}</span>
                    </div>
                    <div class="row align-items-center">
                        <div class="col-auto">
                            <div class="bg-light p-3 rounded-4 border text-success">
                                <i class="fa fa-bullhorn fa-4x"></i>
                            </div>
                        </div>
                        <div class="col">
                            <span class="o_logic_tag mb-2 d-inline-block bg-success">GOOGLE ADS CAMPAIGN</span>
                            
                            <div class="d-flex align-items-center text-muted mt-2 mb-0 fw-medium">
                                <div>
                                    <i class="fa fa-id-badge me-1"></i> ID: <span class="text-dark fw-bold">{rec.google_campaign_id or '—'}</span>
                                </div>
                                <div class="ms-4">
                                    <i class="fa fa-google me-1"></i> Account: <span class="text-dark">{rec.account_id.name or '—'}</span>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <!-- Visual Data Representation -->
                            <div class="o_visual_box">
                                <div class="mb-2 d-flex justify-content-between align-items-end">
                                    <span class="o_visual_label mb-0">Identity Summary</span>
                                    <span class="badge text-bg-success border-0 shadow-sm">Active</span>
                                </div>
                                
                                <div class="mb-2 mt-3">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Reach Power</span>
                                        <span class="o_metric_value text-info">{rec.impressions:,}</span>
                                    </div>
                                    <div class="progress" style="height: 6px;">
                                        <div class="progress-bar bg-info shadow-sm" role="progressbar" style="width: 75%;" aria-valuenow="75" aria-valuemin="0" aria-valuemax="100"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            """
            rec.hero_header_html = Markup(html)

    performance_dashboard_html = fields.Html(compute='_compute_performance_dashboard_html')

    def _compute_performance_dashboard_html(self):
        for rec in self:
            clicks = rec.clicks
            impressions = rec.impressions
            cost = rec.cost
            conversions = rec.conversions
            cost_str = f"{cost:,.0f}" if cost > 0 else "0"
            
            html = f"""
                <div class="o_performance_dashboard py-2">
                    <div class="row g-4 mb-2">
                        <!-- Card 1: Clicks -->
                        <div class="col-md-3 col-sm-6">
                            <div class="o_dashboard_card shadow-sm border-0 rounded-4 h-100 bg-white">
                                <div class="card-body p-3">
                                    <div class="d-flex justify-content-between align-items-center mb-2">
                                        <div class="p-2 rounded-3 bg-primary-subtle d-flex align-items-center justify-content-center" style="width: 42px; height: 42px;">
                                            <i class="fa fa-mouse-pointer text-primary fs-5"></i>
                                        </div>
                                        <span class="badge text-bg-light border-0 small text-muted">CLICKS</span>
                                    </div>
                                    <div class="fs-2 fw-bold text-dark">{clicks:,}</div>
                                    <div class="text-muted small">Lượt Nhấp Chuột</div>
                                  </div>
                            </div>
                        </div>
                        <!-- Card 2: Impressions -->
                        <div class="col-md-3 col-sm-6">
                            <div class="o_dashboard_card shadow-sm border-0 rounded-4 h-100 bg-white">
                                <div class="card-body p-3">
                                    <div class="d-flex justify-content-between align-items-center mb-2">
                                        <div class="p-2 rounded-3 bg-info-subtle d-flex align-items-center justify-content-center" style="width: 42px; height: 42px;">
                                            <i class="fa fa-eye text-info fs-5"></i>
                                        </div>
                                        <span class="badge text-bg-light border-0 small text-muted">VIEWS</span>
                                    </div>
                                    <div class="fs-2 fw-bold text-dark">{impressions:,}</div>
                                    <div class="text-muted small">Lượt Hiển Thị</div>
                                </div>
                            </div>
                        </div>
                        <!-- Card 3: Cost -->
                        <div class="col-md-3 col-sm-6">
                            <div class="o_dashboard_card shadow-sm border-0 rounded-4 h-100 bg-white">
                                <div class="card-body p-3">
                                    <div class="d-flex justify-content-between align-items-center mb-2">
                                        <div class="p-2 rounded-3 bg-danger-subtle d-flex align-items-center justify-content-center" style="width: 42px; height: 42px;">
                                            <i class="fa fa-money text-danger fs-5"></i>
                                        </div>
                                        <span class="badge text-bg-light border-0 small text-muted">SPEND</span>
                                    </div>
                                    <div class="fs-2 fw-bold text-dark text-truncate">{cost_str} đ</div>
                                    <div class="text-muted small">Tổng Chi Phí</div>
                                </div>
                            </div>
                        </div>
                        <!-- Card 4: Conversions -->
                        <div class="col-md-3 col-sm-6">
                            <div class="o_dashboard_card shadow-sm border-0 rounded-4 h-100 bg-white">
                                <div class="card-body p-3">
                                    <div class="d-flex justify-content-between align-items-center mb-2">
                                        <div class="p-2 rounded-3 bg-success-subtle d-flex align-items-center justify-content-center" style="width: 42px; height: 42px;">
                                            <i class="fa fa-shopping-cart text-success fs-5"></i>
                                        </div>
                                        <span class="badge text-bg-light border-0 small text-muted">ORDERS</span>
                                    </div>
                                    <div class="fs-2 fw-bold text-dark">{conversions:,}</div>
                                    <div class="text-muted small">Lượt Chuyển Đổi</div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            """
            rec.performance_dashboard_html = Markup(html)
            
    def write(self, vals):
        # Odoo 18 automation: product_ids is now computed via feed_line_ids.
        # No manual sync logic needed here.
        return super().write(vals)

    def action_sync_to_google(self):
        """Đồng bộ chiến dịch sang Google Ads (CREATE hoặc UPDATE)"""
        self.ensure_one()
        
        if not self.channel_type or self.channel_type == 'UNKNOWN':
            raise UserError(_("Vui lòng chọn 'Loại Kênh' hợp lệ (ví dụ: Tìm kiếm, Hiển thị, PMax...) trước khi đồng bộ lên Google Ads."))

        if self.account_id.is_demo:
            self.google_campaign_id = f"DEMO_SYNC_{self.id}"
            self.state = 'synced'
            self.message_post(body=_("[DEMO] Chiến dịch đã được giả lập đồng bộ thành công."))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Đồng Bộ DEMO'),
                    'message': _('Đã giả lập tạo chiến dịch thành công (Không ảnh hưởng tới Google Ads thật).'),
                    'type': 'success',
                    'sticky': False,
                }
            }

        client = self.account_id._get_google_ads_client()
        customer_id = self.account_id.operating_customer_id
        
        if self.channel_type == 'SHOPPING' and not self.account_id.merchant_center_id:
            raise UserError(_("Vui lòng cấu hình Merchant Center ID trong mục Cài đặt Tài khoản Google Ads để tạo chiến dịch Mua Sắm!"))
        
        # Determine the effective sub-type to send
        sub_type = False
        if self.channel_type == 'VIDEO':
            sub_type = self.video_sub_type
        elif self.channel_type == 'MULTI_CHANNEL':
            sub_type = self.app_sub_type
        elif self.channel_type == 'SMART':
            sub_type = 'SMART_CAMPAIGN' # Smart campaigns require this specific sub-type

        vals = {
            'name': self.name,
            'channel_type': self.channel_type,
            'channel_sub_type': sub_type,
            'merchant_center_id': self.account_id.merchant_center_id,
            'budget_amount': self.budget_amount,
            'business_name': self.business_name,
            'logo_image': self.logo_image,
            'final_url': self.final_url,
            'app_id': self.app_id,
            'app_store': self.app_store,
            'app_bidding_goal': self.app_bidding_goal,
            'marketing_image': self.marketing_image,
            'pmax_headline_1': self.pmax_headline_1,
            'pmax_headline_2': self.pmax_headline_2,
            'pmax_headline_3': self.pmax_headline_3,
            'pmax_long_headline': self.pmax_long_headline,
            'pmax_description_1': self.pmax_description_1,
            'pmax_description_2': self.pmax_description_2,
        }
        
        _logger.info("Syncing campaign %s (type: %s) to Google Ads for Customer %s", self.name, self.channel_type, customer_id)
        
        from ..services.google_ads_mutate import GoogleAdsMutateService
        # Nếu đã có ID Google, thực hiện UPDATE
        if self.google_campaign_id:
            google_resource_name = f"customers/{customer_id}/campaigns/{self.google_campaign_id}"
            ok, result = GoogleAdsMutateService.update_campaign(client, customer_id, google_resource_name, vals)
            if ok and vals.get('budget_amount'):
                GoogleAdsMutateService.update_campaign_budget(client, customer_id, google_resource_name, int(vals['budget_amount'] * 1000000))
        else:
            # Nếu chưa có ID, thử tìm theo tên trên Google ADS trước khi tạo mới
            _logger.info("Searching for existing campaign by name: %s", self.name)
            existing_resource_name = GoogleAdsMutateService.find_campaign_by_name(client, customer_id, self.name)
            
            if existing_resource_name:
                # Nếu tìm thấy, liên kết ID và thực hiện UPDATE
                google_id = existing_resource_name.split('/')[-1]
                self.write({
                    'google_campaign_id': google_id,
                    'state': 'synced',
                })
                _logger.info("Found existing campaign %s. Auto-linked.", google_id)
                ok, result = GoogleAdsMutateService.update_campaign(client, customer_id, existing_resource_name, vals)
                if ok and vals.get('budget_amount'):
                    GoogleAdsMutateService.update_campaign_budget(client, customer_id, existing_resource_name, int(vals['budget_amount'] * 1000000))
            else:
                # Nếu thực sự không có, mới thực hiện CREATE
                ok, result = GoogleAdsMutateService.create_campaign(client, customer_id, vals)
        
        if ok:
            # result is the resource name like "customers/123/campaigns/456"
            google_id = result.split('/')[-1]
            self.write({
                'google_campaign_id': google_id,
                'state': 'synced',
            })
            self.message_post(body=_("Chiến dịch đã được tạo/cập nhật trên Google Ads. ID: %s") % google_id)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Đồng Bộ Thành Công'),
                    'message': _('Chiến dịch đã được đẩy lên hệ thống Google Ads thành công. (ID: %s)') % google_id,
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            hint = ""
            error_msg = result
            if 'ADVERTISING_CHANNEL_TYPE_NOT_AVAILABLE_FOR_ACCOUNT_TYPE' in result:
                error_msg = _("Tài khoản Google Ads hiện chưa được phép tạo loại chiến dịch này trực tiếp (thường gặp ở tài khoản mới hoặc tài khoản ở chế độ Thông minh - Smart Mode).")
            elif 'MUTATE_NOT_ALLOWED' in result:
                error_msg = _("Google Ads hiện tại không cho phép tạo loại chiến dịch này qua API cho tài khoản. Vui lòng kiểm tra lại quyền truy cập hoặc tạo trước trên Google Ads.")
            elif 'ASPECT_RATIO_NOT_ALLOWED' in result:
                error_msg = _("Hình ảnh bạn tải lên làm Logo không đúng tỷ lệ. Google Ads yêu cầu Logo phải có tỷ lệ vuông (1:1). Vui lòng cắt lại ảnh thành hình vuông trước khi tải lên.")
            elif 'MISSING_PROTOCOL' in result:
                error_msg = _("URL trang đích bị thiếu giao thức. Vui lòng thêm 'https://' hoặc 'http://' vào trước URL (ví dụ: https://aaaa.com).")
            elif 'REQUIRED_BUSINESS_NAME_ASSET_NOT_LINKED' in result or 'REQUIRED_LOGO_ASSET_NOT_LINKED' in result:
                error_msg = _("Chiến dịch PMax yêu cầu Tên thương hiệu và Logo. Vui lòng điền đủ 'Tên thương hiệu' và tải 'Logo hình vuông' trong phần Cấu hình Google Ads.")
            elif "RESOURCE_NOT_FOUND" in result and "merchant_id" in result:
                error_msg = _("%s\n\n💡 GỢI Ý: Lỗi 'Resource was not found' ở merchant_id thường do:\n"
                         "1. Merchant Center ID (%s) chưa được LIÊN KẾT với tài khoản Google Ads này.\n"
                         "2. ID Merchant Center bị nhập sai.\n"
                         "Vui lòng kiểm tra lại cấu hình trong cài đặt Tài khoản Google Ads.") % (result, self.account_id.merchant_center_id)
            
            _logger.error("Sync to Google failed for %s: %s", self.name, result)
            raise UserError(_("Đồng bộ thất bại: %s") % error_msg)

    def action_ask_adsroid(self, is_cron=False):
        """Gửi dữ liệu chiến dịch lên Adsroid API để xin nhận định"""
        self.ensure_one()
        if self.state == 'draft':
            if is_cron: return False
            raise UserError(_("Chiến dịch chưa được đồng bộ với Google. Chạy Adsroid cần chiến dịch đã đồng bộ (có ID)."))
        if not self.account_id.use_adsroid:
            if is_cron: return False
            raise UserError(_("Tài khoản chưa bật tính năng tích hợp Adsroid AI!"))
        
        from ..services.adsroid_api import AdsroidApiService
        
        campaign_data = {
            "id": self.google_campaign_id,
            "name": self.name,
            "status": self.status,
            "channel_type": self.channel_type,
            "metrics": {
                "clicks": self.clicks,
                "impressions": self.impressions,
                "cost": self.cost,
                "conversions": self.conversions,
                "roas": self.roas,
            }
        }
        
        # Lấy thông tin sản phẩm trong chiến dịch (từ Product Feed)
        product_data = []
        for line in self.feed_line_ids:
            product_data.append({
                "product_code": line.product_id.default_code,
                "qty_available": line.qty_available,
                "margin_percent": line.margin_percent,
                "avg_daily_sales": line.avg_daily_sales,
                "stock_status": line.stock_status,
            })
            
        success, result = AdsroidApiService.analyze_campaign(
            self.account_id.adsroid_api_key, 
            self.account_id.adsroid_organisation_id,
            self.account_id.adsroid_project_id,
            campaign_data, 
            product_data,
            is_demo=self.account_id.is_demo
        )

        
        if success:
            action = result.get('suggested_action', 'MAINTAIN')
            log_vals = {
                'campaign_id': self.id,
                'score': result.get('score', 0),
                'suggested_action': action,
                'insight': result.get('insight', 'Không có nội dung.'),
                'is_applied': False,
            }
            
            # --- Auto-Apply Logic ---
            if self.account_id.auto_apply_adsroid_action:
                if action == 'PAUSE':
                    if self.account_id.is_demo:
                        self.status = 'paused'
                        log_vals['is_applied'] = True
                        log_vals['insight'] += "\n\n[DEMO] Hệ thống đã tự động PAUSE chiến dịch."
                    else:
                        client = self.account_id._get_google_ads_client()
                        from ..services.google_ads_mutate import GoogleAdsMutateService
                        ok, res = GoogleAdsMutateService.pause_campaign(client, self.account_id.operating_customer_id, self.google_campaign_id)
                        if ok:
                            self.status = 'paused'
                            log_vals['is_applied'] = True
                            log_vals['insight'] += "\n\n[Thành Công] Hệ thống đã tự động PAUSE chiến dịch trên Google Ads."
                        else:
                            log_vals['insight'] += f"\n\n[Lỗi Auto-Apply]: {res}"
            
            # Tạo log lịch sử
            self.env['google.ads.adsroid.log'].create(log_vals)

            insight_html = f"""
                <div class="alert alert-success">
                    <strong>Điểm đánh giá (Score):</strong> {result.get('score', 0)}/100<br/>
                    <strong>Hành động đề xuất:</strong> <span class="badge text-bg-warning">{action}</span><br/>
                    <strong>Nhận định từ AI:</strong><br/>
                    {result.get('insight', 'Không có nội dung.')}
                </div>
            """
            self.adsroid_last_insight = Markup(insight_html)
            self.message_post(body=Markup(_("<b>Adsroid AI Insight:</b><br/>%s")) % Markup(insight_html))
            
            if not is_cron:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Adsroid Đã Phân Tích'),
                        'message': _('Đã nhận được phản hồi từ AI Agent và lưu vào lịch sử.'),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            return True
        else:
            if is_cron: return False
            raise UserError(_("Không thể lấy nhận định từ Adsroid: %s") % result)

    def action_pause_on_google(self):
        self.ensure_one()
        if not self.google_campaign_id: return
        client = self.account_id._get_google_ads_client()
        customer_id = self.account_id.operating_customer_id
        from ..services.google_ads_mutate import GoogleAdsMutateService
        ok, res = GoogleAdsMutateService.pause_campaign(client, customer_id, self.google_campaign_id)
        if ok:
            self.status = 'paused'
            return True
        raise UserError(_("Không thể tạm dừng trên Google Ads: %s") % res)

    def action_enable_on_google(self):
        self.ensure_one()
        if not self.google_campaign_id: return
        client = self.account_id._get_google_ads_client()
        customer_id = self.account_id.operating_customer_id
        from ..services.google_ads_mutate import GoogleAdsMutateService
        ok, res = GoogleAdsMutateService.enable_campaign(client, customer_id, self.google_campaign_id)
        if ok:
            self.status = 'enabled'
            return True
        raise UserError(_("Không thể kích hoạt trên Google Ads: %s") % res)

    def action_remove_from_google_only(self):
        """Xóa trên Google Ads nhưng giữ lại bản ghi Odoo dưới dạng Nháp"""
        self.ensure_one()
        if not self.google_campaign_id: return
        client = self.account_id._get_google_ads_client()
        customer_id = self.account_id.operating_customer_id
        from ..services.google_ads_mutate import GoogleAdsMutateService
        ok, res = GoogleAdsMutateService.remove_campaign(client, customer_id, self.google_campaign_id)
        if ok:
            self.write({
                'google_campaign_id': False,
                'state': 'draft',
                'status': 'removed'
            })
            self.message_post(body=_("Đã xóa chiến dịch trên Google Ads. Bản ghi Odoo đã chuyển về trạng thái Nháp."))
            return True
        raise UserError(_("Không thể xóa trên Google Ads: %s") % res)

    def unlink(self):
        """Khi xóa trên Odoo, thực hiện xóa vĩnh viễn trên Google Ads nếu đã đồng bộ"""
        for rec in self:
            if rec.google_campaign_id and rec.account_id.state == 'authenticated':
                try:
                    client = rec.account_id.get_google_ads_client()
                    customer_id = rec.account_id.google_customer_id
                    from ..services.google_ads_mutate import GoogleAdsMutateService
                    ok, result = GoogleAdsMutateService.remove_campaign(client, customer_id, rec.google_campaign_id)
                    if ok:
                        _logger.info("Deleted campaign %s from Google Ads via Odoo unlink.", rec.google_campaign_id)
                    else:
                        _logger.warning("Could not delete campaign %s from Google Ads: %s", rec.google_campaign_id, result)
                except Exception as e:
                    _logger.error("Error during unlink sync for campaign %s: %s", rec.id, str(e))
        return super().unlink()

    _sql_constraints = [
        ('google_campaign_id_uniq', 'unique(google_campaign_id)', 'Google Campaign ID phải là duy nhất!'),
    ]
