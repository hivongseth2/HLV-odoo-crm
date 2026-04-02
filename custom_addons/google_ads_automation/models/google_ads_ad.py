from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)

class GoogleAdsAd(models.Model):
    _name = 'google.ads.ad'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Mẫu Quảng Cáo'

    hero_header_html = fields.Html(compute='_compute_hero_header_html')
    performance_dashboard_html = fields.Html(compute='_compute_performance_dashboard_html')

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
                                    <i class="fa fa-info-circle me-1"></i> Type: <span class="text-dark">{rec.type_id.name or rec.type}</span>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="o_visual_box">
                                <span class="o_visual_label mb-3">Phân tích tương tác</span>
                                <div class="mb-3">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Tỷ lệ ra đơn</span>
                                        <span class="o_metric_value text-warning">{rec.conversion_rate:.2f}%</span>
                                    </div>
                                    <div class="progress mt-1" style="height: 6px;">
                                        <div class="progress-bar bg-warning" style="width: {cr_width}%"></div>
                                    </div>
                                </div>
                                <div class="mb-0">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">ROAS dự tính</span>
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
                            <div class="o_metric_sub_label text-primary"><i class="fa fa-mouse-pointer me-1"></i>Interaction</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="o_premium_metric_card">
                            <div class="o_metric_label">Impressions</div>
                            <div class="o_metric_value">{rec.impressions:,}</div>
                            <div class="o_metric_sub_label text-info"><i class="fa fa-eye me-1"></i>Visibility</div>
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
                            <div class="o_metric_sub_label text-danger"><i class="fa fa-bank me-1"></i>Total Spent</div>
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
    ], string='Trạng thái bộ máy', default='draft', required=True, tracking=True)
    product_ids = fields.Many2many('product.template', 'google_ads_ad_product_rel', 
                                    'ad_id', 'product_id', string='Sản Phẩm')

    status = fields.Selection([
        ('unspecified', 'Chưa xác định'),
        ('unknown', 'Không rõ'),
        ('enabled', 'Đang hoạt động'),
        ('paused', 'Tạm dừng'),
        ('removed', 'Đã xóa'),
    ], string='Trạng Thái', default='paused', tracking=True)

    type_id = fields.Many2one('google.ads.ad.type', string='Loại Quảng Cáo', required=True)
    type = fields.Char(string='Mã Loại (Tech)', related='type_id.code', store=True, readonly=True)

    final_urls = fields.Char(string='URL Đích (Final URL)', tracking=True)
    
    # Creation fields
    headline = fields.Text(string='Tiêu đề (Mỗi dòng 1 tiêu đề)', 
                           help='RSA: >3 tiêu đề (max 30 ký tự). Discovery: Tiêu đề (max 40 ký tự).')
    description = fields.Text(string='Mô tả (Mỗi dòng 1 mô tả)', 
                              help='RSA: >2 mô tả (max 90 ký tự). Discovery: Mô tả (max 160 ký tự).')

    # Validation Computed Fields for UI
    headline_count = fields.Integer(compute='_compute_validation_stats', string='Số lượng Tiêu đề')
    description_count = fields.Integer(compute='_compute_validation_stats', string='Số lượng Mô tả')
    is_final_url_invalid = fields.Boolean(compute='_compute_validation_stats', string='URL không hợp lệ')
    is_ad_content_invalid = fields.Boolean(compute='_compute_validation_stats', string='Quảng cáo không hợp lệ')

    @api.depends('headline', 'description', 'final_urls', 'type_id')
    def _compute_validation_stats(self):
        for rec in self:
            headlines = [h.strip() for h in (rec.headline or "").split('\n') if h.strip()]
            descriptions = [d.strip() for d in (rec.description or "").split('\n') if d.strip()]
            h_unique = list(dict.fromkeys(headlines))
            d_unique = list(dict.fromkeys(descriptions))
            rec.headline_count = len(h_unique)
            rec.description_count = len(d_unique)
            
            url = (rec.final_urls or "").strip()
            rec.is_final_url_invalid = bool(url and not (url.startswith('http://') or url.startswith('https://')))
            
            if rec.type == 'RESPONSIVE_SEARCH_AD':
                rec.is_ad_content_invalid = (rec.headline_count < 3 or rec.description_count < 2 or not rec.final_urls or rec.is_final_url_invalid)
            elif rec.type == 'DISCOVERY_RESPONSIVE_AD':
                rec.is_ad_content_invalid = (rec.headline_count < 1 or rec.description_count < 1 or not rec.final_urls or rec.is_final_url_invalid)
            else:
                rec.is_ad_content_invalid = False

    # Metrics
    clicks = fields.Integer(string='Lượt Nhấp', default=0, readonly=True)
    impressions = fields.Integer(string='Lượt Hiển Thị', default=0, readonly=True)
    cost = fields.Float(string='Chi Phí', default=0.0, readonly=True)
    conversions = fields.Float(string='Lượt Chuyển Đổi', default=0.0, readonly=True)

    # Computed Metrics for UI
    conversion_rate = fields.Float(string='Tỷ Lệ Chuyển Đổi (%)', compute='_compute_performance_metrics', store=False)
    roas = fields.Float(string='ROAS', compute='_compute_performance_metrics', store=False)
    
    @api.depends('clicks', 'conversions', 'cost')
    def _compute_performance_metrics(self):
        for rec in self:
            rec.conversion_rate = (rec.conversions / rec.clicks * 100) if rec.clicks > 0 else 0.0
            rec.roas = (rec.conversions * 500000 / rec.cost) if rec.cost > 0 else 0.0

    @api.onchange('type_id')
    def _onchange_type_id_filter_groups(self):
        if not self.type_id: return {'domain': {'ad_group_id': []}}
        if self.type_id.compatible_ad_group_types:
            res_types = self.type_id.compatible_ad_group_types.split(',')
            return {'domain': {'ad_group_id': [('type', 'in', res_types)]}}
        return {'domain': {'ad_group_id': []}}

    @api.onchange('ad_group_id')
    def _onchange_ad_group_id_filter_types(self):
        if not self.ad_group_id: return {'domain': {'type_id': []}}
        ad_group_type = self.ad_group_id.type
        domain = [('compatible_ad_group_types', 'ilike', ad_group_type)]
        if self.type_id and ad_group_type not in (self.type_id.compatible_ad_group_types or ''):
            default_type = self.env['google.ads.ad.type'].search(domain, limit=1)
            self.type_id = default_type
            return {
                'domain': {'type_id': domain},
                'warning': {
                    'title': _("Loại quảng cáo không tương thích"),
                    'message': _("Nhóm quảng cáo '%s' hỗ trợ: %s. Hệ thống đã chuyển về '%s'.") % (self.ad_group_id.name, ad_group_type, default_type.name)
                }
            }
        return {'domain': {'type_id': domain}}

    def action_sync_to_google(self):
        self.ensure_one()
        cam = self.ad_group_id.campaign_id
        
        # Chặn đồng bộ cho các loại chiến dịch mà Google tự quản lý Ad
        if cam.channel_type in ['SHOPPING', 'PERFORMANCE_MAX', 'SMART']:
            raise UserError(_("Chiến dịch loại '%s' tự động quản lý mẫu quảng cáo. Bạn không cần (và không thể) đồng bộ thủ công mẫu quảng cáo cho loại này.") % cam.channel_type)

        if self.ad_group_id.state == 'draft':
            raise UserError(_("Vui lòng đồng bộ Nhóm quảng cáo cha trước."))

        account = self.ad_group_id.campaign_id.account_id
        if account.is_demo:
            self.google_ad_id = f"DEMO_AD_SYNC_{self.id}"
            self.state = 'synced'
            return True

        headlines = list(dict.fromkeys([h.strip() for h in (self.headline or "").split('\n') if h.strip()]))
        descriptions = list(dict.fromkeys([d.strip() for d in (self.description or "").split('\n') if d.strip()]))
        
        final_url = (self.final_urls or "").strip()
        if final_url and not (final_url.startswith('http')):
            final_url = 'https://' + final_url
            self.final_urls = final_url

        if not final_url:
            raise UserError(_("Vui lòng nhập URL Đích (Final URL)."))

        client = account._get_google_ads_client()
        customer_id = account.operating_customer_id
        from ..services.google_ads_mutate import GoogleAdsMutateService

        vals = {
            'type': self.type,
            'headlines': headlines,
            'descriptions': descriptions,
            'final_url': final_url,
        }

        # Discovery (Demand Gen) Specific Assets
        if self.type == 'DISCOVERY_RESPONSIVE_AD':
            cam = self.ad_group_id.campaign_id
            vals['business_name'] = cam.business_name or account.name[:25]
            
            # Upload images from Campaign if available
            if cam.marketing_image:
                vals['marketing_image_asset'] = GoogleAdsMutateService._create_image_asset(client, customer_id, cam.marketing_image, "Discovery Marketing", target_ratio=1.91)
            if cam.logo_image:
                vals['logo_image_asset'] = GoogleAdsMutateService._create_image_asset(client, customer_id, cam.logo_image, "Discovery Logo", target_ratio=1.0)
                vals['square_marketing_image_asset'] = vals['logo_image_asset'] # Square is often same as logo for simple sync

            if not vals.get('marketing_image_asset'):
                raise UserError(_("Quảng cáo Khám phá yêu cầu 'Ảnh quảng cáo (Ngang)' trong cấu hình Chiến dịch."))
            if not vals.get('logo_image_asset'):
                raise UserError(_("Quảng cáo Khám phá yêu cầu 'Logo hình vuông' trong cấu hình Chiến dịch."))
            if not cam.business_name:
                raise UserError(_("Quảng cáo Khám phá yêu cầu 'Tên thương hiệu' trong cấu hình Chiến dịch."))

        # Sync Action
        if self.google_ad_id:
            ok, result = GoogleAdsMutateService.update_ad(client, customer_id, self.ad_group_id.google_ad_group_id, self.google_ad_id, vals)
        else:
            ok, result = GoogleAdsMutateService.create_ad(client, customer_id, self.ad_group_id.google_ad_group_id, vals)
        
        if ok:
            if not self.google_ad_id:
                self.write({'google_ad_id': result.split('/')[-1], 'state': 'synced'})
            self.message_post(body=_("Đồng bộ thành công lên Google Ads: %s") % result)
            return True
        else:
            error_hint = result
            if 'OPERATION_NOT_PERMITTED_FOR_CONTEXT' in result and 'OWNED_AND_OPERATED' in result:
                error_hint = _("Lỗi ngữ cảnh: Bạn đang cố gắng tạo mẫu quảng cáo không phù hợp với chiến dịch Khám phá (Discovery). \n\n"
                               "💡 Cách khắc phục: Hãy đảm bảo bạn đã chọn đúng 'Loại quảng cáo' là 'Mẫu quảng cáo Khám phá' và đã điền đủ Tiêu đề/Mô tả/Hình ảnh.")
            elif 'IMMUTABLE_FIELD' in result:
                error_hint = _("Lỗi đồng bộ: Trường dữ liệu không thể thay đổi (Immutable). \n\n"
                               "💡 Nguyên nhân: Loại mẫu quảng cáo này không cho phép tạo thủ công trong nhóm quảng cáo hiện tại (thường gặp ở chiến dịch Shopping hoặc Smart).")
            raise UserError(_("Đồng bộ Ad thất bại: %s") % error_hint)

    def action_pause_on_google(self):
        self.ensure_one()
        if not self.google_ad_id: return
        account = self.ad_group_id.campaign_id.account_id
        client = account._get_google_ads_client()
        customer_id = account.operating_customer_id
        from ..services.google_ads_mutate import GoogleAdsMutateService
        ok, res = GoogleAdsMutateService.pause_ad(client, customer_id, self.ad_group_id.google_ad_group_id, self.google_ad_id)
        if ok:
            self.status = 'paused'
            return True
        raise UserError(_("Không thể tạm dừng Mẫu quảng cáo trên Google Ads: %s") % res)

    def action_enable_on_google(self):
        self.ensure_one()
        if not self.google_ad_id: return
        account = self.ad_group_id.campaign_id.account_id
        client = account._get_google_ads_client()
        customer_id = account.operating_customer_id
        from ..services.google_ads_mutate import GoogleAdsMutateService
        ok, res = GoogleAdsMutateService.enable_ad(client, customer_id, self.ad_group_id.google_ad_group_id, self.google_ad_id)
        if ok:
            self.status = 'enabled'
            return True
        raise UserError(_("Không thể kích hoạt Mẫu quảng cáo trên Google Ads: %s") % res)

    def action_remove_from_google_only(self):
        """Xóa trên Google Ads nhưng giữ lại bản ghi Odoo dưới dạng Nháp"""
        self.ensure_one()
        if not self.google_ad_id: return
        account = self.ad_group_id.campaign_id.account_id
        client = account._get_google_ads_client()
        customer_id = account.operating_customer_id
        from ..services.google_ads_mutate import GoogleAdsMutateService
        ok, res = GoogleAdsMutateService.remove_ad(client, customer_id, self.ad_group_id.google_ad_group_id, self.google_ad_id)
        if ok:
            self.write({
                'google_ad_id': False,
                'state': 'draft',
                'status': 'removed'
            })
            self.message_post(body=_("Đã xóa Mẫu quảng cáo trên Google Ads. Bản ghi Odoo đã chuyển về trạng thái Nháp."))
            return True
        raise UserError(_("Không thể xóa Mẫu quảng cáo trên Google Ads: %s") % res)

    def unlink(self):
        """Khi xóa mẫu quảng cáo trên Odoo, xóa trên Google Ads"""
        for rec in self:
            if rec.google_ad_id and rec.ad_group_id.campaign_id.account_id.state == 'authenticated':
                try:
                    account = rec.ad_group_id.campaign_id.account_id
                    client = account.get_google_ads_client()
                    customer_id = account.google_customer_id
                    from ..services.google_ads_mutate import GoogleAdsMutateService
                    ok, result = GoogleAdsMutateService.remove_ad(client, customer_id, rec.ad_group_id.google_ad_group_id, rec.google_ad_id)
                    if ok:
                        _logger.info("Deleted ad %s from Google Ads.", rec.google_ad_id)
                    else:
                        _logger.warning("Could not delete ad %s: %s", rec.google_ad_id, result)
                except Exception as e:
                    _logger.error("Error during ad unlink sync: %s", str(e))
        return super().unlink()

    _sql_constraints = [
        ('google_ad_id_uniq', 'unique(google_ad_id)', 'Google Ad ID phải là duy nhất!'),
    ]
