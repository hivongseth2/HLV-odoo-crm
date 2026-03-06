from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup
import logging
import random

_logger = logging.getLogger(__name__)

try:
    from google.ads.googleads.client import GoogleAdsClient
    from google.ads.googleads.errors import GoogleAdsException
except ImportError:
    _logger.warning("Google Ads API Python client missing. Please run `pip install google-ads`.")
    GoogleAdsClient = None
    GoogleAdsException = None

class GoogleAdsAccount(models.Model):
    _name = 'google.ads.account'
    _description = 'Tài khoản Google Ads API'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Tên Tài Khoản', required=True)
    active = fields.Boolean(default=True, string='Kích Hoạt')

    # ── Demo Mode ────────────────────────────────
    is_demo = fields.Boolean(
        string='Chế Độ Demo',
        default=False,
        tracking=True,
        help='Bật để test mà không cần tài khoản Google Ads thật. '
             'Hệ thống sẽ tự tạo Campaigns/Ad Groups/Ads giả với metrics ngẫu nhiên.',
    )

    # API Credentials (không bắt buộc khi is_demo)
    developer_token = fields.Char(string='Developer Token', tracking=True)
    client_id = fields.Char(string='Client ID')
    client_secret = fields.Char(string='Client Secret')
    refresh_token = fields.Char(string='Refresh Token')
    login_customer_id = fields.Char(
        string='Login Customer ID (MCC)',
        help='ID của tài khoản người quản lý (MCC). Định dạng: 1234567890 (không có dấu -)'
    )
    operating_customer_id = fields.Char(
        string='Operating Customer ID',
        help='ID của tài khoản Ads bạn muốn quản lý trực tiếp. Định dạng: 1234567890 (không có dấu -)'
    )
    
    service_account_json = fields.Text(
        string='File JSON Service Account',
        help='Dành cho các kết nối liên quan đến Google Analytics, GTM, v.v.',
    )

    state = fields.Selection([
        ('draft', 'Nháp'),
        ('connected', 'Đã Kết Nối'),
        ('error', 'Lỗi')
    ], string='Trạng Thái', default='draft', tracking=True)

    # ── KPI Dashboard Fields (Computed) ─────────
    campaign_ids = fields.One2many('google.ads.campaign', 'account_id', string='Chiến Dịch')
    
    total_spend = fields.Float(string='Tổng Chi Phí', compute='_compute_account_kpis')
    total_conversions = fields.Float(string='Tổng Chuyển Đổi', compute='_compute_account_kpis')
    total_campaigns = fields.Integer(string='Số Chiến Dịch', compute='_compute_account_kpis')
    account_roas = fields.Float(string='ROAS Trung Bình', compute='_compute_account_kpis')

    @api.depends('campaign_ids', 'campaign_ids.cost', 'campaign_ids.conversions')
    def _compute_account_kpis(self):
        for rec in self:
            camps = rec.campaign_ids
            rec.total_campaigns = len(camps)
            rec.total_spend = sum(camps.mapped('cost'))
            rec.total_conversions = sum(camps.mapped('conversions'))
            
            # Simple ROAS: (Total Conversions * 500k) / Total Spend
            if rec.total_spend > 0:
                rec.account_roas = (rec.total_conversions * 500000) / rec.total_spend
            else:
                rec.account_roas = 0.0

    state_label = fields.Char(compute='_compute_state_label')

    @api.depends('state')
    def _compute_state_label(self):
        selection = dict(self._fields['state'].selection)
        for rec in self:
            rec.state_label = selection.get(rec.state, rec.state)

    hero_header_html = fields.Html(compute='_compute_hero_header_html')

    def _compute_hero_header_html(self):
        for rec in self:
            state_color = 'bg-success' if rec.state == 'connected' else 'bg-warning' if rec.state == 'draft' else 'bg-danger'
            demo_badge = Markup('<span class="ms-3 badge text-bg-warning">MODO DEMO</span>') if rec.is_demo else ''
            
            # Performance visualization
            max_roas_goal = 5.0
            roas_progress = min((rec.account_roas / max_roas_goal) * 100, 100) if max_roas_goal > 0 else 0
            
            # Simple visualization of campaign count vs active
            active_camps = len(rec.campaign_ids.filtered(lambda c: c.status == 'enabled'))
            camp_progress = (active_camps / rec.total_campaigns * 100) if rec.total_campaigns > 0 else 0
            
            html = f"""
                <div class="o_hero_header">
                    <div class="status_badge">
                        <span class="o_status_ping {state_color}"></span>
                        <span class="badge text-bg-light fw-bold shadow-sm">{rec.state_label}</span>
                    </div>
                    <div class="row align-items-center">
                        <div class="col-auto">
                            <div class="bg-white p-3 rounded-4 shadow-sm">
                                <i class="fa fa-google fa-4x text-primary"></i>
                            </div>
                        </div>
                        <div class="col">
                            <span class="badge rounded-pill text-bg-primary mb-2 px-3 py-2">GOOGLE ADS API HUB</span>
                            <h1 class="text-white mt-1">
                                {rec.name}
                            </h1>
                            <p class="text-white-50 mt-2 mb-0 fw-medium">
                                <i class="fa fa-id-card-o me-1"></i> ID: 
                                <span class="text-white fw-bold">{rec.operating_customer_id or '—'}</span>
                                {demo_badge}
                            </p>
                        </div>
                        <div class="col-md-5">
                            <div class="o_visual_box">
                                <span class="o_visual_label">Account Performance Grid</span>
                                
                                <div class="mb-3">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Average Account ROAS</span>
                                        <span class="o_metric_value">{rec.account_roas:.2f}x</span>
                                    </div>
                                    <div class="progress" style="height: 8px;">
                                        <div class="progress-bar bg-info" style="width: {roas_progress}%"></div>
                                    </div>
                                </div>
                                
                                <div class="mb-0">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Active Campaigns Ratio</span>
                                        <span class="o_metric_value">{active_camps}/{rec.total_campaigns}</span>
                                    </div>
                                    <div class="progress" style="height: 8px;">
                                        <div class="progress-bar bg-success" style="width: {camp_progress}%"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            """
            rec.hero_header_html = Markup(html)

    def _get_google_ads_client(self):
        """Build Google Ads Client from credentials"""
        self.ensure_one()
        if not GoogleAdsClient:
            raise UserError(_("Thư viện Python 'google-ads' chưa được cài đặt. Vui lòng liên hệ quản trị hệ thống (Chạy: pip install google-ads)."))
        
        credentials = {
            "developer_token": self.developer_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "login_customer_id": self.login_customer_id,
            "use_proto_plus": True
        }
        
        try:
            return GoogleAdsClient.load_from_dict(credentials, version="v15")
        except Exception as e:
            raise UserError(_("Không thể khởi tạo Google Ads Client. Chi tiết lỗi: %s") % str(e))

    def action_test_connection(self):
        self.ensure_one()

        # ── Demo shortcut ────────────────────────
        if self.is_demo:
            self.state = 'connected'
            self.message_post(body=_(
                "[DEMO MODE] Kết nối giả lập thành công! "
                "Bấm 'Đồng Bộ Dữ Liệu' để tạo Campaigns/Ad Groups/Ads mẫu."
            ))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('DEMO — Thành Công'),
                    'message': _('Đã kết nối ở chế độ Demo. Không cần tài khoản Google Ads thật.'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        # ── Real mode ───────────────────────────
        client = self._get_google_ads_client()
        customer_service = client.get_service("CustomerService")
        
        # We try to load a customer to verify credentials. We will use the operating_customer_id.
        resource_name = customer_service.customer_path(self.operating_customer_id)
        
        try:
            response = customer_service.get_customer(resource_name=resource_name)
            self.state = 'connected'
            self.message_post(body=_("Kết nối thành công! Đã kết nối với tài khoản: %s") % response.descriptive_name)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Thành Công'),
                    'message': _('Kết nối thành công tới tài khoản: %s') % response.descriptive_name,
                    'type': 'success',
                    'sticky': False,
                }
            }
        except GoogleAdsException as ex:
            error_details = []
            for error in ex.failure.errors:
                error_details.append(f"{error.error_code}: {error.message}")
            self.state = 'error'
            raise UserError(_("Lỗi Google Ads API: \n%s") % '\n'.join(error_details))
        except Exception as e:
            self.state = 'error'
            raise UserError(_("Kết nối thất bại: %s") % str(e))

    def action_sync_all_data(self):
        """Đồng bộ toàn bộ Dữ liệu Chiến dịch & Chỉ số hiệu suất"""
        self.ensure_one()

        if self.is_demo:
            self._demo_seed_all()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('DEMO — Đồng bộ Hoàn tất'),
                    'message': _('Đã tạo dữ liệu mẫu: 4 Campaigns, Nhóm QC và Ads tương ứng.'),
                    'type': 'success',
                    'sticky': False,
                }
            }

        self.action_sync_campaigns()
        self.action_sync_ad_groups()
        self.action_sync_ads()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đồng bộ Hoàn tất'),
                'message': _('Đã đồng bộ toàn bộ dữ liệu (Chiến dịch, Nhóm QC, Quảng Cáo, Chỉ số).'),
                'type': 'success',
                'sticky': False,
            }
        }

    # ─────────────────────────────────────────────
    # DEMO MODE — Seed fake data
    # ─────────────────────────────────────────────
    def _demo_seed_all(self):
        """Tạo Campaigns/Ad Groups/Ads giả với metrics ngẫu nhiên"""
        self.ensure_one()
        self._demo_seed_campaigns()
        self._demo_seed_ad_groups()
        self._demo_seed_ads()
        self._demo_seed_conversions()
        self.message_post(body=_(
            "[DEMO] Đã tạo dữ liệu mẫu: 4 Campaigns, 8 Nhóm QC, 12 Ads, ~15 Lượt Chuyển Đổi từ WooCommerce giả."
        ))

    def _demo_seed_campaigns(self):
        """Tạo 4 campaigns giả"""
        self.ensure_one()
        Campaign = self.env['google.ads.campaign']

        demo_campaigns = [
            {'name': '[DEMO] Tìm kiếm — Sản phẩm A', 'status': 'enabled',  'channel': 'SEARCH'},
            {'name': '[DEMO] Tìm kiếm — Sản phẩm B', 'status': 'enabled',  'channel': 'SEARCH'},
            {'name': '[DEMO] Display — Remarketing',   'status': 'paused',   'channel': 'DISPLAY'},
            {'name': '[DEMO] Performance Max',          'status': 'enabled',  'channel': 'PERFORMANCE_MAX'},
        ]

        for i, c in enumerate(demo_campaigns, start=1):
            gid = f'DEMO_{self.id}_{i}'
            existing = Campaign.search([('google_campaign_id', '=', gid)], limit=1)
            vals = {
                'name': c['name'],
                'account_id': self.id,
                'google_campaign_id': gid,
                'status': c['status'],
                'channel_type': c['channel'],
                'clicks':      random.randint(50,  800),
                'impressions': random.randint(500, 20000),
                'cost':        round(random.uniform(100000, 3000000), 0),
                'conversions': round(random.uniform(0, 25), 1),
            }
            if existing:
                existing.write(vals)
            else:
                Campaign.create(vals)

    def _demo_seed_ad_groups(self):
        """Tạo 2 ad groups cho mỗi campaign demo"""
        self.ensure_one()
        Campaign = self.env['google.ads.campaign']
        AdGroup  = self.env['google.ads.ad.group']

        campaigns = Campaign.search([('google_campaign_id', 'like', f'DEMO_{self.id}_')])
        for camp in campaigns:
            for j in range(1, 3):
                gid = f'{camp.google_campaign_id}_AG{j}'
                existing = AdGroup.search([('google_ad_group_id', '=', gid)], limit=1)
                vals = {
                    'name': f'{camp.name} — Nhóm {j}',
                    'campaign_id': camp.id,
                    'google_ad_group_id': gid,
                    'status': 'enabled',
                    'type': 'SEARCH_STANDARD',
                    'clicks':      random.randint(10, 300),
                    'impressions': random.randint(100, 8000),
                    'cost':        round(random.uniform(50000, 1000000), 0),
                    'conversions': round(random.uniform(0, 10), 1),
                }
                if existing:
                    existing.write(vals)
                else:
                    AdGroup.create(vals)

    def _demo_seed_ads(self):
        """Tạo 1-2 ads cho mỗi ad group demo"""
        self.ensure_one()
        Campaign = self.env['google.ads.campaign']
        Ad       = self.env['google.ads.ad']

        campaigns = Campaign.search([('google_campaign_id', 'like', f'DEMO_{self.id}_')])
        ad_groups = self.env['google.ads.ad.group'].search([
            ('campaign_id', 'in', campaigns.ids)
        ])
        for ag in ad_groups:
            for k in range(1, 3):
                gid = f'{ag.google_ad_group_id}_AD{k}'
                existing = Ad.search([('google_ad_id', '=', gid)], limit=1)
                vals = {
                    'name': f'{ag.name} — Mẫu QC {k}',
                    'ad_group_id': ag.id,
                    'google_ad_id': gid,
                    'status': 'enabled',
                    'type': 'RESPONSIVE_SEARCH_AD',
                    'final_urls': 'https://example.com/san-pham',
                    'clicks':      random.randint(5,  150),
                    'impressions': random.randint(50, 3000),
                    'cost':        round(random.uniform(20000, 500000), 0),
                    'conversions': round(random.uniform(0, 5), 1),
                }
                if existing:
                    existing.write(vals)
                else:
                    Ad.create(vals)

    def _demo_seed_conversions(self):
        """Tạo 15 đơn hàng WooCommerce giả phân bổ cho các campaign demo"""
        from datetime import timedelta
        self.ensure_one()
        Conversion = self.env['google.ads.conversion']
        Campaign = self.env['google.ads.campaign']

        campaigns = Campaign.search([('google_campaign_id', 'like', f'DEMO_{self.id}_')])
        if not campaigns:
            return

        fake_products = [
            'Giày Nam Thể Thao Speed X2', 'Giày Nữ Sneaker Air', 'Dép Quai Hậu Nam',
            'Ba Lô Du Lịch 45L', 'Túi Xách Nữ Công Sở', 'Ví Nam Da Thật',
            'Áo Thun Nam Polo', 'Quần Short Thể Thao', 'Nón Lưỡi Trai Basic',
        ]
        fake_customers = [
            'Nguyễn Văn An', 'Trần Thị Bình', 'Lê Hoàng Cường', 'Phạm Minh Đức',
            'Hoàng Thị Lan', 'Vũ Quốc Tuấn', 'Đặng Thị Mai', 'Bùi Văn Hùng',
            'Lý Thị Hoa', 'Đinh Văn Khoa',
        ]
        statuses = ['completed', 'completed', 'completed', 'processing', 'cancelled']
        today = fields.Datetime.now()

        for i in range(1, 16):
            camp = campaigns[i % len(campaigns)]
            days_ago = random.randint(0, 30)
            order_date = today - timedelta(days=days_ago)
            product = random.choice(fake_products)
            customer = random.choice(fake_customers)
            status = random.choice(statuses)
            revenue = round(random.uniform(200000, 3000000), 0) if status != 'cancelled' else 0
            gclid = f'DEMO_GCLID_{self.id}_{i}_{random.randint(1000, 9999)}'

            order_ref = f'DEMO-WC-{self.id}-{i:04d}'
            existing = Conversion.search([('order_ref', '=', order_ref)], limit=1)
            vals = {
                'source': 'demo',
                'account_id': self.id,
                'campaign_id': camp.id,
                'order_ref': order_ref,
                'order_date': order_date,
                'revenue': revenue,
                'product_names': product,
                'customer_name': customer,
                'order_status': status,
                'gclid': gclid,
            }
            if existing:
                existing.write(vals)
            else:
                Conversion.create(vals)

    def action_sync_campaigns(self):
        self.ensure_one()
        client = self._get_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")
        
        # Lấy chiến dịch kèm chỉ số cơ bản (metrics) của ngày hôm nay
        # hoặc có thể tuỳ chọn lấy metrics 30 ngày (sẽ xử lý nâng cao sau)
        query = """
            SELECT
              campaign.id,
              campaign.name,
              campaign.status,
              campaign.advertising_channel_type,
              metrics.clicks,
              metrics.impressions,
              metrics.cost_micros,
              metrics.conversions
            FROM campaign
            WHERE segments.date DURING YESTERDAY
            ORDER BY campaign.id
        """
        
        try:
            stream = ga_service.search_stream(customer_id=self.operating_customer_id, query=query)
            
            campaign_obj = self.env['google.ads.campaign']
            synced_count = 0
            for batch in stream:
                for row in batch.results:
                    campaign = row.campaign
                    metrics = row.metrics
                    
                    status_name = campaign.status.name.lower() # UNKNOWN, UNSPECIFIED, ENABLED, PAUSED, REMOVED
                    
                    vals = {
                        'name': campaign.name,
                        'account_id': self.id,
                        'google_campaign_id': str(campaign.id),
                        'status': status_name,
                        'channel_type': campaign.advertising_channel_type.name,
                        'clicks': metrics.clicks,
                        'impressions': metrics.impressions,
                        'cost': metrics.cost_micros / 1000000.0,
                        'conversions': metrics.conversions,
                    }
                    
                    existing = campaign_obj.search([('google_campaign_id', '=', str(campaign.id))], limit=1)
                    if existing:
                        existing.write(vals)
                    else:
                        campaign_obj.create(vals)
                    synced_count += 1
            
            self.message_post(body=_("Đã đồng bộ %s chiến dịch.") % synced_count)
            return True
            
        except GoogleAdsException as ex:
            raise UserError(_("Không thể lấy dữ liệu chiến dịch. Lỗi API Google Ads: %s") % str(ex))

    def action_sync_ad_groups(self):
        self.ensure_one()
        client = self._get_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")
        
        query = """
            SELECT
              campaign.id,
              ad_group.id,
              ad_group.name,
              ad_group.status,
              ad_group.type,
              metrics.clicks,
              metrics.impressions,
              metrics.cost_micros,
              metrics.conversions
            FROM ad_group
            WHERE segments.date DURING YESTERDAY
            ORDER BY ad_group.id
        """
        
        try:
            stream = ga_service.search_stream(customer_id=self.operating_customer_id, query=query)
            
            ad_group_obj = self.env['google.ads.ad.group']
            campaign_obj = self.env['google.ads.campaign']
            
            synced_count = 0
            for batch in stream:
                for row in batch.results:
                    ad_group = row.ad_group
                    campaign = row.campaign
                    metrics = row.metrics
                    
                    status_name = ad_group.status.name.lower()
                    
                    # Cần lấy ID chiến dịch nội bộ của Odoo
                    campaign_record = campaign_obj.search([('google_campaign_id', '=', str(campaign.id))], limit=1)
                    if not campaign_record:
                        continue # Bỏ qua nếu chưa đồng bộ campaign này
                    
                    vals = {
                        'name': ad_group.name,
                        'campaign_id': campaign_record.id,
                        'google_ad_group_id': str(ad_group.id),
                        'status': status_name,
                        'type': ad_group.type_.name if hasattr(ad_group, 'type_') else 'UNKNOWN',
                        'clicks': metrics.clicks,
                        'impressions': metrics.impressions,
                        'cost': metrics.cost_micros / 1000000.0,
                        'conversions': metrics.conversions,
                    }
                    
                    existing = ad_group_obj.search([('google_ad_group_id', '=', str(ad_group.id))], limit=1)
                    if existing:
                        existing.write(vals)
                    else:
                        ad_group_obj.create(vals)
                    synced_count += 1
            
            self.message_post(body=_("Đã đồng bộ %s nhóm quảng cáo.") % synced_count)
            return True
            
        except GoogleAdsException as ex:
            raise UserError(_("Không thể lấy dữ liệu nhóm quảng cáo. Lỗi API: %s") % str(ex))

    def action_sync_ads(self):
        self.ensure_one()
        client = self._get_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")
        
        query = """
            SELECT
              ad_group.id,
              ad_group_ad.ad.id,
              ad_group_ad.ad.name,
              ad_group_ad.status,
              ad_group_ad.ad.type,
              ad_group_ad.ad.final_urls,
              metrics.clicks,
              metrics.impressions,
              metrics.cost_micros,
              metrics.conversions
            FROM ad_group_ad
            WHERE segments.date DURING YESTERDAY
            ORDER BY ad_group_ad.ad.id
        """
        
        try:
            stream = ga_service.search_stream(customer_id=self.operating_customer_id, query=query)
            
            ad_obj = self.env['google.ads.ad']
            ad_group_obj = self.env['google.ads.ad.group']
            
            synced_count = 0
            for batch in stream:
                for row in batch.results:
                    ad_group_ad = row.ad_group_ad
                    ad = ad_group_ad.ad
                    ad_group = row.ad_group
                    metrics = row.metrics
                    
                    status_name = ad_group_ad.status.name.lower()
                    
                    # Cần lấy ID Ad Group nội bộ của Odoo
                    ad_group_record = ad_group_obj.search([('google_ad_group_id', '=', str(ad_group.id))], limit=1)
                    if not ad_group_record:
                        continue 
                    
                    final_urls = ", ".join(ad.final_urls) if getattr(ad, 'final_urls', None) else ""
                    
                    vals = {
                        'name': ad.name or f"Ad {ad.id}",
                        'ad_group_id': ad_group_record.id,
                        'google_ad_id': str(ad.id),
                        'status': status_name,
                        'type': ad.type_.name if hasattr(ad, 'type_') else 'UNKNOWN',
                        'final_urls': final_urls,
                        'clicks': metrics.clicks,
                        'impressions': metrics.impressions,
                        'cost': metrics.cost_micros / 1000000.0,
                        'conversions': metrics.conversions,
                    }
                    
                    existing = ad_obj.search([('google_ad_id', '=', str(ad.id))], limit=1)
                    if existing:
                        existing.write(vals)
                    else:
                        ad_obj.create(vals)
                    synced_count += 1
            
            self.message_post(body=_("Đã đồng bộ %s mẫu quảng cáo.") % synced_count)
            return True
            
        except GoogleAdsException as ex:
            raise UserError(_("Không thể lấy dữ liệu mẫu quảng cáo. Lỗi API: %s") % str(ex))
