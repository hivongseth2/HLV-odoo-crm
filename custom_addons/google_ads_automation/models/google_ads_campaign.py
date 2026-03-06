from odoo import api, fields, models, _
from markupsafe import Markup

class GoogleAdsCampaign(models.Model):
    _name = 'google.ads.campaign'
    _description = 'Chiến dịch Google Ads'

    name = fields.Char(string='Tên Chiến Dịch', required=True)
    account_id = fields.Many2one('google.ads.account', string='Tài Khoản Google Ads', required=True, ondelete='cascade')
    google_campaign_id = fields.Char(string='Google Campaign ID', required=True, index=True)

    status = fields.Selection([
        ('unspecified', 'Chưa xác định'),
        ('unknown', 'Không rõ'),
        ('enabled', 'Đang hoạt động'),
        ('paused', 'Tạm dừng'),
        ('removed', 'Đã xóa'),
    ], string='Trạng Thái', default='unknown')

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
    ], string='Loại Kênh', help='Loại kênh quảng cáo từ Google Ads')

    # Metrics (Chỉ số hiệu suất cơ bản)
    clicks = fields.Integer(string='Lượt Nhấp', default=0)
    impressions = fields.Integer(string='Lượt Hiển Thị', default=0)
    cost = fields.Float(string='Chi Phí', default=0.0)
    conversions = fields.Float(string='Lượt Chuyển Đổi', default=0.0)

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
                <div class="o_hero_header" style="background: linear-gradient(135deg, #10B981 0%, #065F46 100%);">
                    <div class="status_badge">
                        <span class="o_status_ping {status_color}"></span>
                        <span class="badge text-bg-light fw-bold shadow-sm">{rec.status_label}</span>
                    </div>
                    <div class="row align-items-center">
                        <div class="col-auto">
                            <div class="bg-white p-3 rounded-4 shadow-sm text-success">
                                <i class="fa fa-bullhorn fa-4x"></i>
                            </div>
                        </div>
                        <div class="col">
                            <span class="badge rounded-pill text-bg-success mb-2 px-3 py-2">GOOGLE ADS CAMPAIGN</span>
                            <h1 class="text-white mt-1">
                                {rec.name}
                            </h1>
                            <div class="d-flex align-items-center text-white-50 mt-2 mb-0 fw-medium">
                                <div>
                                    <i class="fa fa-id-badge me-1"></i> ID: <span class="text-white fw-bold">{rec.google_campaign_id or '—'}</span>
                                </div>
                                <div class="ms-4">
                                    <i class="fa fa-google me-1"></i> Account: <span class="text-white">{rec.account_id.name or '—'}</span>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <!-- Visual Data Representation -->
                            <div class="bg-black bg-opacity-25 p-3 rounded-3 text-white">
                                <div class="mb-2 d-flex justify-content-between align-items-end">
                                    <small class="text-white-50 fw-bold uppercase">Visualized Performance</small>
                                    <span class="badge text-bg-success border-0 shadow-sm">Real-time</span>
                                </div>
                                
                                <div class="mb-2">
                                    <div class="d-flex justify-content-between small mb-1">
                                        <span>ROAS Performance</span>
                                        <span class="fw-bold">{rec.roas:.1f}x</span>
                                    </div>
                                    <div class="progress" style="height: 6px; background: rgba(255,255,255,0.1);">
                                        <div class="progress-bar bg-info shadow-sm" role="progressbar" style="width: {roas_width}%; border-radius: 3px;" aria-valuenow="{roas_width}" aria-valuemin="0" aria-valuemax="100"></div>
                                    </div>
                                </div>
                                
                                <div>
                                    <div class="d-flex justify-content-between small mb-1">
                                        <span>Conv. Rate</span>
                                        <span class="fw-bold">{rec.conversion_rate:.2f}%</span>
                                    </div>
                                    <div class="progress" style="height: 6px; background: rgba(255,255,255,0.1);">
                                        <div class="progress-bar bg-warning shadow-sm" role="progressbar" style="width: {cr_width}%; border-radius: 3px;" aria-valuenow="{cr_width}" aria-valuemin="0" aria-valuemax="100"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            """
            rec.hero_header_html = Markup(html)

    _sql_constraints = [
        ('google_campaign_id_uniq', 'unique(google_campaign_id)', 'Google Campaign ID phải là duy nhất!'),
    ]
