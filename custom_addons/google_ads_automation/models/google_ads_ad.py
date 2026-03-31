from odoo import api, fields, models, _
from odoo.exceptions import UserError
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
    headline = fields.Text(string='Tiêu đề (Mỗi dòng 1 tiêu đề)', 
                           help='Yêu cầu ít nhất 3 tiêu đề duy nhất cho quảng cáo RSA. Hệ thống sẽ tự động loại bỏ các dòng trống hoặc trùng lặp. Mỗi tiêu đề không quá 30 ký tự.')
    description = fields.Text(string='Mô tả (Mỗi dòng 1 mô tả)', 
                              help='Yêu cầu ít nhất 2 mô tả duy nhất cho quảng cáo RSA. Hệ thống sẽ tự động loại bỏ các dòng trống hoặc trùng lặp. Mỗi mô tả không quá 90 ký tự.')

    # Validation Computed Fields for UI
    headline_count = fields.Integer(compute='_compute_validation_stats', string='Số lượng Tiêu đề')
    description_count = fields.Integer(compute='_compute_validation_stats', string='Số lượng Mô tả')
    is_final_url_invalid = fields.Boolean(compute='_compute_validation_stats', string='URL không hợp lệ')
    is_rsa_invalid = fields.Boolean(compute='_compute_validation_stats', string='Quảng cáo không hợp lệ')

    @api.depends('headline', 'description', 'final_urls', 'type')
    def _compute_validation_stats(self):
        for rec in self:
            # RSA specific validation
            headlines = [h.strip() for h in (rec.headline or "").split('\n') if h.strip()]
            descriptions = [d.strip() for d in (rec.description or "").split('\n') if d.strip()]
            
            # Unique counts (deduplication)
            h_unique = list(dict.fromkeys(headlines))
            d_unique = list(dict.fromkeys(descriptions))
            
            rec.headline_count = len(h_unique)
            rec.description_count = len(d_unique)
            
            # URL Validation (Missing Protocol check)
            url = (rec.final_urls or "").strip()
            rec.is_final_url_invalid = bool(url and not (url.startswith('http://') or url.startswith('https://')))
            
            # Overall RSA validity
            if rec.type == 'RESPONSIVE_SEARCH_AD':
                rec.is_rsa_invalid = (
                    rec.headline_count < 3 or 
                    rec.description_count < 2 or 
                    not rec.final_urls or 
                    rec.is_final_url_invalid
                )
            else:
                rec.is_rsa_invalid = False

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
        if self.ad_group_id.state == 'draft':
            raise UserError(_("Vui lòng đồng bộ Nhóm quảng cáo cha trước."))

        account = self.ad_group_id.campaign_id.account_id
        if account.is_demo:
            self.google_ad_id = f"DEMO_AD_SYNC_{self.id}"
            self.state = 'synced'
            return True

        # 1. Clean & Deduplicate Data
        headlines = [h.strip() for h in (self.headline or "").split('\n') if h.strip()]
        descriptions = [d.strip() for d in (self.description or "").split('\n') if d.strip()]
        
        # Deduplication preserving order
        unique_headlines = list(dict.fromkeys(headlines))
        unique_descriptions = list(dict.fromkeys(descriptions))
        
        # 2. Fix Final URL (Auto-protocol)
        final_url = (self.final_urls or "").strip()
        if final_url and not (final_url.startswith('http://') or final_url.startswith('https://')):
            final_url = 'https://' + final_url
            self.final_urls = final_url # Save fix to DB

        # 3. Final Validation with specific errors
        if len(unique_headlines) < 3:
            raise UserError(_("Quảng cáo RSA yêu cầu ít nhất 3 tiêu đề KHÁC NHAU. Mỗi tiêu đề 1 dòng.\n"
                              "Hiện tại bạn mới có %s tiêu đề hợp lệ.") % len(unique_headlines))
            
        if len(unique_descriptions) < 2:
            raise UserError(_("Quảng cáo RSA yêu cầu ít nhất 2 mô tả KHÁC NHAU. Mỗi mô tả 1 dòng.\n"
                              "Hiện tại bạn mới có %s mô tả hợp lệ.") % len(unique_descriptions))
            
        if not final_url:
            raise UserError(_("Vui lòng nhập URL Đích (Final URL) trước khi đồng bộ."))

        client = account._get_google_ads_client()
        customer_id = account.operating_customer_id
        
        vals = {
            'headlines': unique_headlines,
            'descriptions': unique_descriptions,
            'final_url': final_url,
        }
        
        from ..services.google_ads_mutate import GoogleAdsMutateService
        
        if self.google_ad_id:
            # Update existing ad
            ok, result = GoogleAdsMutateService.update_ad(
                client, customer_id, self.ad_group_id.google_ad_group_id, self.google_ad_id, vals
            )
        else:
            # Create new ad
            ok, result = GoogleAdsMutateService.create_ad(
                client, customer_id, self.ad_group_id.google_ad_group_id, vals
            )
        
        if ok:
            if not self.google_ad_id:
                self.write({'google_ad_id': result.split('/')[-1], 'state': 'synced'})
            # Notify user of success
            self.message_post(body=_("Đồng bộ thành công lên Google Ads: %s") % result)
        else:
            raise UserError(_("Đồng bộ Ad thất bại (Lưu ý: Headlines/Descriptions có thể trùng lặp hoặc quá dài): \n %s") % result)

    _sql_constraints = [
        ('google_ad_id_uniq', 'unique(google_ad_id)', 'Google Ad ID phải là duy nhất!'),
    ]
