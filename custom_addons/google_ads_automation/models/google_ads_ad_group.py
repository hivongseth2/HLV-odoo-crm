from odoo import api, fields, models, _
from markupsafe import Markup

class GoogleAdsAdGroup(models.Model):
    _name = 'google.ads.ad.group'
    _description = 'Nhóm Quảng Cáo'

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
                                <i class="fa fa-object-group fa-4x"></i>
                            </div>
                        </div>
                        <div class="col">
                            <span class="o_logic_tag mb-2 d-inline-block bg-primary">GOOGLE AD GROUP</span>
                            
                            <div class="d-flex align-items-center text-muted mt-2 mb-0 fw-medium">
                                <div>
                                    <i class="fa fa-bullhorn me-1"></i> Campaign: <span class="text-dark">{rec.campaign_id.name or '—'}</span>
                                </div>
                                <div class="ms-4">
                                    <i class="fa fa-tags me-1"></i> Type: <span class="text-dark">{dict(self._fields['type'].selection).get(rec.type, rec.type)}</span>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="o_visual_box">
                                <span class="o_visual_label mb-3">Group Performance Analytics</span>
                                <div class="mb-3">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Conv. Rate</span>
                                        <span class="o_metric_value text-warning">{rec.conversion_rate:.2f}%</span>
                                    </div>
                                    <div class="progress mt-1" style="height: 6px;">
                                        <div class="progress-bar bg-warning" style="width: {cr_width}%"></div>
                                    </div>
                                </div>
                                <div class="mb-0">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Group ROAS</span>
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

    name = fields.Char(string='Tên Nhóm Quảng Cáo', required=True)
    campaign_id = fields.Many2one('google.ads.campaign', string='Chiến Dịch', required=True, ondelete='cascade', readonly=True)
    google_ad_group_id = fields.Char(string='Google Ad Group ID', required=True, index=True, readonly=True)
    product_ids = fields.Many2many('product.template', 'google_ads_ad_group_product_rel', 
                                    'ad_group_id', 'product_id', string='Sản Phẩm')

    status = fields.Selection([
        ('unspecified', 'Chưa xác định'),
        ('unknown', 'Không rõ'),
        ('enabled', 'Đang hoạt động'),
        ('paused', 'Tạm dừng'),
        ('removed', 'Đã xóa'),
    ], string='Trạng Thái', default='unknown', readonly=True)

    type = fields.Selection([
        ('SEARCH_STANDARD',         'Tìm Kiếm Chuẩn'),
        ('SEARCH_DYNAMIC_ADS',      'Tìm Kiếm Động (DSA)'),
        ('DISPLAY_STANDARD',        'Hiển Thị Chuẩn'),
        ('SHOPPING_PRODUCT_ADS',    'Mua Sắm — Sản Phẩm'),
        ('SHOPPING_SMART_ADS',      'Mua Sắm Thông Minh'),
        ('VIDEO_TRUE_VIEW_IN_STREAM', 'Video In-Stream'),
        ('VIDEO_BUMPER',            'Video Bumper (6 giây)'),
        ('VIDEO_OUTSTREAM',         'Video Outstream'),
        ('HOTEL_ADS',               'Khách Sạn'),
        ('DISCOVERY',               'Khám Phá'),
        ('UNKNOWN',                 'Không rõ'),
    ], string='Loại Nhóm Quảng Cáo', readonly=True)

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

    _sql_constraints = [
        ('google_ad_group_id_uniq', 'unique(google_ad_group_id)', 'Google Ad Group ID phải là duy nhất!'),
    ]
