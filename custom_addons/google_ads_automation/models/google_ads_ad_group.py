from odoo import api, fields, models, _
from odoo.exceptions import UserError
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
                                    <i class="fa fa-tags me-1"></i> Type: <span class="text-dark">{rec.type_id.name or rec.type or '—'}</span>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="o_visual_box">
                                <span class="o_visual_label mb-3">Identity Summary</span>
                                <div class="mb-3">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Reach Power</span>
                                        <span class="o_metric_value text-info">{rec.impressions:,}</span>
                                    </div>
                                    <div class="progress mt-1" style="height: 6px;">
                                        <div class="progress-bar bg-info" style="width: 75%"></div>
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

    name = fields.Char(string='Tên Nhóm Quảng Cáo', required=True)
    campaign_id = fields.Many2one('google.ads.campaign', string='Chiến Dịch', required=True, ondelete='cascade')
    campaign_channel_type = fields.Selection(related='campaign_id.channel_type', string='Loại Kênh Chiến Dịch', store=False)
    google_ad_group_id = fields.Char(string='Google Ad Group ID', index=True, readonly=True)
    state = fields.Selection([
        ('draft', 'Nháp (Local)'),
        ('synced', 'Đã đồng bộ Google'),
    ], string='Trạng thái bộ máy', default='draft', required=True)
    product_ids = fields.Many2many('product.template', 'google_ads_ad_group_product_rel', 
                                    'ad_group_id', 'product_id', string='Sản Phẩm')

    status = fields.Selection([
        ('unspecified', 'Chưa xác định'),
        ('unknown', 'Không rõ'),
        ('enabled', 'Đang hoạt động'),
        ('paused', 'Tạm dừng'),
        ('removed', 'Đã xóa'),
    ], string='Trạng Thái', default='paused')

    type_id = fields.Many2one('google.ads.ad.group.type', string='Loại Nhóm Quảng Cáo', required=True)
    type = fields.Char(string='Mã Loại (Tech)', related='type_id.code', store=True, readonly=True)

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

    @api.onchange('campaign_id')
    def _onchange_campaign_id_clear_type(self):
        """Khi đổi chiến dịch, nếu loại nhóm hiện tại không còn phù hợp thì xóa trắng để chọn lại"""
        if self.campaign_id and self.type_id:
            channel_type = self.campaign_id.channel_type
            if channel_type not in (self.type_id.compatible_channel_types or ''):
                self.type_id = False
                # Không đưa thông báo Warning tự động sửa để tôn trọng ý người dùng, chỉ xóa trắng để họ chọn lại
                
    def action_sync_to_google(self):
        self.ensure_one()
        if self.state == 'synced': return True
        if self.campaign_id.state == 'draft':
            raise UserError(_("Vui lòng đồng bộ Chiến dịch cha trước."))

        if self.campaign_id.channel_type in ['PERFORMANCE_MAX', 'SMART', 'MULTI_CHANNEL']:
            raise UserError(_("Chiến dịch '%s' (loại: %s) không sử dụng 'Nhóm quảng cáo' truyền thống. "
                              "Loại chiến dịch này quản lý quảng cáo và mục tiêu tự động hoặc qua Nhóm thành phần (Asset Group). "
                              "Vui lòng chọn Chiến dịch Tìm kiếm, Hiển thị hoặc Video chuẩn.") % (self.campaign_id.name, self.campaign_id.channel_type))

        if self.campaign_id.account_id.is_demo:
            self.google_ad_group_id = f"DEMO_AG_SYNC_{self.id}"
            self.state = 'synced'
            return True

        client = self.campaign_id.account_id._get_google_ads_client()
        customer_id = self.campaign_id.account_id.operating_customer_id
        
        if not self.type_id:
            raise UserError(_("Vui lòng chọn 'Loại Nhóm Quảng Cáo' phù hợp với Chiến dịch trước khi đồng bộ."))

        vals = {
            'name': self.name,
            'status': self.status,
            'type': self.type,
        }
        from ..services.google_ads_mutate import GoogleAdsMutateService
        ok, result = GoogleAdsMutateService.create_ad_group(
            client, customer_id, self.campaign_id.google_campaign_id, vals
        )
        
        if ok:
            self.write({'google_ad_group_id': result.split('/')[-1], 'state': 'synced'})
        else:
            error_msg = result
            if 'CANNOT_ADD_ADGROUP_OF_TYPE_DSA_TO_CAMPAIGN_WITHOUT_DSA_SETTING' in result:
                error_msg = _("Loại nhóm 'Tìm kiếm động (DSA)' chỉ dùng được với các Chiến dịch đã bật cấu hình DSA. Vui lòng chọn loại 'Tìm kiếm chuẩn' hoặc đổi Chiến dịch.")
            elif 'DUPLICATE_ADGROUP_NAME' in result:
                error_msg = _("Tên nhóm quảng cáo này bị trùng trong chiến dịch. Vui lòng đổi tên khác.")
            elif 'OPERATION_NOT_PERMITTED_FOR_CONTEXT' in result:
                error_msg = _("Loại nhóm quảng cáo này không được hỗ trợ cho Chiến dịch hiện tại (ví dụ: Chiến dịch PMax/Video không dùng Nhóm Tìm kiếm chuẩn).")

            raise UserError(_("Đồng bộ Ad Group thất bại: %s") % error_msg)

    _sql_constraints = [
        ('google_ad_group_id_uniq', 'unique(google_ad_group_id)', 'Google Ad Group ID phải là duy nhất!'),
    ]
