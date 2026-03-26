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
    google_campaign_id = fields.Char(string='Google Campaign ID', index=True, readonly=True)
    state = fields.Selection([
        ('draft', 'Nháp (Local)'),
        ('synced', 'Đã đồng bộ Google'),
    ], string='Trạng thái bộ máy', default='draft', required=True, tracking=True)
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

    @api.depends('feed_line_ids.product_id')
    def _compute_product_ids(self):
        for rec in self:
            rec.product_ids = rec.feed_line_ids.mapped('product_id')


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
        ('MULTI_CHANNEL',   'Đa Kênh (UAC)'),
        ('LOCAL',           'Địa Phương (Local)'),
        ('SMART',           'Thông Minh (Smart)'),
        ('PERFORMANCE_MAX', 'Tối Đa Hiệu Suất (PMax)'),
        ('DISCOVERY',       'Khám Phá (Discovery)'),
        ('HOTEL',           'Khách Sạn (Hotel)'),
        ('UNKNOWN',         'Không rõ'),
    ], string='Loại Kênh', help='Loại kênh quảng cáo từ Google Ads', readonly=True, default='SEARCH')

    # Cấu hình Chiến dịch (Dùng để tạo mới/cập nhật)
    budget_amount = fields.Float(string='Ngân sách hàng ngày', default=50000.0, tracking=True)
    business_name = fields.Char(string='Tên thương hiệu', help='Yêu cầu cho PMax nếu bật Brand Guidelines', tracking=True)
    logo_image = fields.Binary(string='Logo hình vuông', help='Yêu cầu cho PMax (tỷ lệ 1:1)', tracking=True)
    final_url = fields.Char(string='URL trang đích', help='Link web của anh', tracking=True)

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
                                    <span class="o_visual_label mb-0">Visualized Performance</span>
                                    <span class="badge text-bg-success border-0 shadow-sm">Real-time</span>
                                </div>
                                
                                <div class="mb-2 mt-3">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">ROAS Performance</span>
                                        <span class="o_metric_value">{rec.roas:.1f}x</span>
                                    </div>
                                    <div class="progress" style="height: 6px;">
                                        <div class="progress-bar bg-info shadow-sm" role="progressbar" style="width: {roas_width}%;" aria-valuenow="{roas_width}" aria-valuemin="0" aria-valuemax="100"></div>
                                    </div>
                                </div>
                                
                                <div class="mt-3">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Conv. Rate</span>
                                        <span class="o_metric_value">{rec.conversion_rate:.2f}%</span>
                                    </div>
                                    <div class="progress" style="height: 6px;">
                                        <div class="progress-bar bg-warning shadow-sm" role="progressbar" style="width: {cr_width}%;" aria-valuenow="{cr_width}" aria-valuemin="0" aria-valuemax="100"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            """
            rec.hero_header_html = Markup(html)
            
    def write(self, vals):
        # Odoo 18 automation: product_ids is now computed via feed_line_ids.
        # No manual sync logic needed here.
        return super().write(vals)

    def action_sync_to_google(self):
        """Đồng bộ chiến dịch sang Google Ads (CREATE hoặc UPDATE)"""
        self.ensure_one()
        
        if not self.channel_type or self.channel_type == 'UNKNOWN':
            raise UserError(_("Vui lòng chọn 'Loại Kênh' hợp lệ (ví dụ: Tìm kiếm, Hiển thị, PMax...) trước khi đồng bộ lên Google Ads."))

        if self.state == 'synced' and not self.env.context.get('force_sync'):
            return True

        if self.account_id.is_demo:
            self.google_campaign_id = f"DEMO_SYNC_{self.id}"
            self.state = 'synced'
            self.message_post(body=_("[DEMO] Chiến dịch đã được giả lập đồng bộ thành công."))
            return True

        client = self.account_id._get_google_ads_client()
        customer_id = self.account_id.operating_customer_id
        
        if self.channel_type == 'SHOPPING' and not self.account_id.merchant_center_id:
            raise UserError(_("Vui lòng cấu hình Merchant Center ID trong mục Cài đặt Tài khoản Google Ads để tạo chiến dịch Mua Sắm!"))
        
        vals = {
            'name': self.name,
            'channel_type': self.channel_type,
            'merchant_center_id': self.account_id.merchant_center_id,
            'budget_amount': self.budget_amount,
            'business_name': self.business_name,
            'logo_image': self.logo_image,
            'final_url': self.final_url,
        }
        
        _logger.info("Syncing campaign %s (type: %s) to Google Ads for Customer %s", self.name, self.channel_type, customer_id)
        
        from ..services.google_ads_mutate import GoogleAdsMutateService
        # Nếu đã có ID Google, thực hiện UPDATE
        if self.google_campaign_id:
            google_resource_name = f"customers/{customer_id}/campaigns/{self.google_campaign_id}"
            ok, result = GoogleAdsMutateService.update_campaign(client, customer_id, google_resource_name, vals)
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
            self.message_post(body=_("Chiến dịch đã được tạo trên Google Ads. ID: %s") % google_id)
        else:
            hint = ""
            error_msg = result
            if 'ADVERTISING_CHANNEL_TYPE_NOT_AVAILABLE_FOR_ACCOUNT_TYPE' in result:
                error_msg = _("Tài khoản Google Ads của anh hiện chưa được phép tạo loại chiến dịch này trực tiếp (thường gặp ở tài khoản mới hoặc tài khoản ở chế độ Thông minh - Smart Mode).")
            elif 'MUTATE_NOT_ALLOWED' in result:
                error_msg = _("Google Ads hiện tại không cho phép tạo loại chiến dịch này qua API cho tài khoản của anh. Anh vui lòng kiểm tra lại quyền truy cập hoặc tạo trước trên Google Ads.")
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

    _sql_constraints = [
        ('google_campaign_id_uniq', 'unique(google_campaign_id)', 'Google Campaign ID phải là duy nhất!'),
    ]
