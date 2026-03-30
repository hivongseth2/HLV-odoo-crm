from odoo import api, fields, models, _
from markupsafe import Markup

class GoogleAdsAd(models.Model):
    _name = 'google.ads.ad'
    _description = 'Mẫu Quảng Cáo'

    hero_header_html = fields.Html(compute='_compute_hero_header_html')

    def _compute_hero_header_html(self):
        for rec in self:
            status_color = 'bg-success' if rec.status == 'enabled' else 'bg-warning' if rec.status == 'paused' else 'bg-danger'
            
            # Visualization logic
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
                                <i class="fa fa-newspaper-o fa-4x"></i>
                            </div>
                        </div>
                        <div class="col">
                            <span class="o_logic_tag mb-2 d-inline-block bg-primary">GOOGLE AD CONTENT</span>
                            
                            <div class="d-flex align-items-center text-muted mt-2 mb-0 fw-medium">
                                <div>
                                    <i class="fa fa-folder-open me-1"></i> Ad Group: <span class="text-dark">{rec.ad_group_id.name or '—'}</span>
                                </div>
                                <div class="ms-4">
                                    <i class="fa fa-info-circle me-1"></i> Type: <span class="text-dark">{dict(self._fields['type'].selection).get(rec.type, rec.type)}</span>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="o_visual_box">
                                <span class="o_visual_label mb-3">Ad Interaction Insight</span>
                                <div class="mb-3">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Conversion Rate</span>
                                        <span class="o_metric_value text-warning">{rec.conversion_rate:.2f}%</span>
                                    </div>
                                    <div class="progress mt-1" style="height: 6px;">
                                        <div class="progress-bar bg-warning" style="width: {cr_width}%"></div>
                                    </div>
                                </div>
                                <div class="mb-0">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Estimated ROAS</span>
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

    name = fields.Char(string='Tên/Tiêu Đề Quảng Cáo')
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

    name = fields.Char(string='Tên/Tiêu Đề Quảng Cáo')
    ad_group_id = fields.Many2one('google.ads.ad.group', string='Nhóm Quảng Cáo', required=True, ondelete='cascade')
    google_ad_id = fields.Char(string='Google Ad ID', index=True, readonly=True)
    state = fields.Selection([
        ('draft', 'Nháp (Local)'),
        ('synced', 'Đã đồng bộ Google'),
    ], string='Trạng thái bộ máy', default='draft', required=True)
    product_ids = fields.Many2many('product.template', 'google_ads_ad_product_rel', 
                                    'ad_id', 'product_id', string='Sản Phẩm')

    status = fields.Selection([
        ('unspecified', 'Chưa xác định'),
        ('unknown', 'Không rõ'),
        ('enabled', 'Đang hoạt động'),
        ('paused', 'Tạm dừng'),
        ('removed', 'Đã xóa'),
    ], string='Trạng Thái', default='paused')

    type = fields.Selection([
        ('RESPONSIVE_SEARCH_AD',    'Tìm Kiếm Thích Ứng (RSA)'),
        ('EXPANDED_TEXT_AD',        'Tìm Kiếm Văn Bản Mở Rộng'),
        ('RESPONSIVE_DISPLAY_AD',   'Hiển Thị Thích Ứng'),
        ('IMAGE_AD',                'Quảng Cáo Hình Ảnh'),
        ('VIDEO_AD',                'Quảng Cáo Video'),
        ('SHOPPING_PRODUCT_AD',     'Mua Sắm — Sản Phẩm'),
        ('SHOPPING_SMART_AD',       'Mua Sắm Thông Minh'),
        ('CALL_AD',                 'Quảng Cáo Cuộc Gọi'),
        ('DISCOVERY_AD',            'Khám Phá'),
        ('DISCOVERY_CAROUSEL_AD',   'Khám Phá Dạng Băng Chuyền'),
        ('PERFORMANCE_MAX',         'Tối Đa Hiệu Suất (PMax)'),
        ('UNKNOWN',                 'Không rõ'),
    ], string='Loại Quảng Cáo', default='RESPONSIVE_SEARCH_AD')

    final_urls = fields.Char(string='URL Đích (Final URL)')
    
    # Creation fields
    headline = fields.Char(string='Tiêu đề chính')
    description = fields.Text(string='Mô tả quảng cảo')

    # Metrics
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
        help='Mặc định lấy Conversions * 500k / Cost (Giả định demo)'
    )
    
    @api.depends('clicks', 'conversions', 'cost')
    def _compute_performance_metrics(self):
        for rec in self:
            if rec.clicks > 0:
                rec.conversion_rate = (rec.conversions / rec.clicks) * 100
            else:
                rec.conversion_rate = 0.0
                
            if rec.cost > 0:
                # Giả định doanh thu 500k cho demo
                rec.roas = (rec.conversions * 500000) / rec.cost
            else:
                rec.roas = 0.0

    def action_sync_to_google(self):
        self.ensure_one()
        if self.state == 'synced': return True
        if self.ad_group_id.state == 'draft':
            raise UserError(_("Vui lòng đồng bộ Nhóm quảng cáo cha trước."))

        account = self.ad_group_id.campaign_id.account_id
        if account.is_demo:
            self.google_ad_id = f"DEMO_AD_SYNC_{self.id}"
            self.state = 'synced'
            return True

        client = account._get_google_ads_client()
        customer_id = account.operating_customer_id
        
        vals = {
            'headline': self.headline or self.name,
            'description': self.description or self.name,
            'final_url': self.final_urls,
        }
        from ..services.google_ads_mutate import GoogleAdsMutateService
        ok, result = GoogleAdsMutateService.create_ad(
            client, customer_id, self.ad_group_id.google_ad_group_id, vals
        )
        
        if ok:
            self.write({'google_ad_id': result.split('/')[-1], 'state': 'synced'})
        else:
            raise UserError(_("Đồng bộ Ad thất bại: %s") % result)

    _sql_constraints = [
        ('google_ad_id_uniq', 'unique(google_ad_id)', 'Google Ad ID phải là duy nhất!'),
    ]
