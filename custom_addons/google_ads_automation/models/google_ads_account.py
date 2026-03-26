from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup
import json
import logging
import random
from urllib.parse import urlencode

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

    # ── Adsroid Integration ──────────────────────
    use_adsroid = fields.Boolean(
        string='Sử dụng Adsroid AI',
        default=False,
        tracking=True,
        help='Tích hợp AI Agent Adsroid.com để phân tích và tối ưu hóa chiến dịch tự động.'
    )
    adsroid_api_key = fields.Char(
        string='Adsroid API Key',
        help='API Key lấy từ tài khoản Adsroid của bạn.'
    )
    auto_apply_adsroid_action = fields.Boolean(
        string='Tự động áp dụng đề xuất',
        default=False,
        tracking=True,
        help='Nếu bật, hệ thống sẽ tự động thực thi các đề xuất của AI (như Tạm dừng chiến dịch) ngay khi nhận được Insight.'
    )
    adsroid_organisation_id = fields.Char(
        string='Adsroid Organisation ID',
        help='ID tổ chức lấy từ cài đặt Adsroid.'
    )
    adsroid_project_id = fields.Char(
        string='Adsroid Project ID',
        help='ID dự án lấy từ cài đặt Adsroid.'
    )

    # ── Demo Mode ────────────────────────────────
    is_demo = fields.Boolean(
        string='Chế Độ Demo',
        default=False,
        tracking=True,
        help='Bật để test mà không cần tài khoản Google Ads thật. '
             'Hệ thống sẽ tự tạo Campaigns/Ad Groups/Ads giả với metrics ngẫu nhiên.',
    )

    # API Credentials (không bắt buộc khi is_demo)
    developer_token = fields.Char(string='Developer Token')
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
    merchant_center_id = fields.Char(
        string='Merchant Center ID',
        help='ID Tài khoản Google Merchant Center (bắt buộc cho chiến dịch Mua Sắm / Performance Max)'
    )
    
    @api.onchange('login_customer_id', 'operating_customer_id', 'merchant_center_id', 'client_id', 'client_secret', 'developer_token')
    def _onchange_sanitize_credentials(self):
        """Tự động loại bỏ dấu gạch ngang và khoảng trắng từ các thông tin dán vào."""
        fields_to_sanitize = [
            'login_customer_id', 'operating_customer_id', 'merchant_center_id', 
            'client_id', 'client_secret', 'developer_token',
            'adsroid_organisation_id', 'adsroid_project_id'
        ]
        for field in fields_to_sanitize:
            val = getattr(self, field)
            if val:
                # Với Customer ID: xóa gạch ngang và spaces
                if 'customer_id' in field:
                    setattr(self, field, val.replace('-', '').replace(' ', '').strip())
                else:
                    # Với Token/Secret: chỉ strip spaces
                    setattr(self, field, val.strip())

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
                        <span class="badge text-bg-light fw-bold shadow-sm border">{rec.state_label}</span>
                    </div>
                    <div class="row align-items-center">
                        <div class="col-auto">
                            <div class="bg-light p-3 rounded-4 border text-primary">
                                <i class="fa fa-google fa-4x"></i>
                            </div>
                        </div>
                        <div class="col">
                            <span class="o_logic_tag mb-2 d-inline-block bg-primary">GOOGLE ADS API HUB</span>
                            <h1 class="mt-1 text-primary">
                                {rec.name}
                            </h1>
                            <p class="text-muted mt-2 mb-0 fw-medium">
                                <i class="fa fa-id-card-o me-1"></i> ID: 
                                <span class="text-dark fw-bold">{rec.operating_customer_id or '—'}</span>
                                {demo_badge}
                            </p>
                        </div>
                        <div class="col-md-5">
                            <div class="o_visual_box">
                                <span class="o_visual_label mb-3">Account Performance Grid</span>
                                
                                <div class="mb-3">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Average Account ROAS</span>
                                        <span class="o_metric_value text-info">{rec.account_roas:.2f}x</span>
                                    </div>
                                    <div class="progress mt-1" style="height: 8px;">
                                        <div class="progress-bar bg-info" style="width: {roas_progress}%"></div>
                                    </div>
                                </div>
                                
                                <div class="mb-0">
                                    <div class="o_metric_row">
                                        <span class="o_metric_title">Active Campaigns Ratio</span>
                                        <span class="o_metric_value text-success">{active_camps}/{rec.total_campaigns}</span>
                                    </div>
                                    <div class="progress mt-1" style="height: 8px;">
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
            "use_proto_plus": True
        }
        if self.login_customer_id:
            credentials["login_customer_id"] = self.login_customer_id.replace('-', '').replace(' ', '').strip()
        
        # ── Debug Logging (Masked) ──────────────────
        _logger.info("Building Google Ads Client for Account: %s (ID: %s)", self.name, self.id)
        _logger.info(" - Operating Customer ID: %s", self.operating_customer_id)
        _logger.info(" - Login Customer ID (MCC): %s", self.login_customer_id)
        _logger.info(" - Developer Token: %s...%s", (self.developer_token or "")[:5], (self.developer_token or "")[-3:])
        _logger.info(" - Client ID: %s...%s", (self.client_id or "")[:10], (self.client_id or "")[-5:])
        
        try:
            # 1. Thử để thư viện tự nhận diện phiên bản mới nhất (với google-ads bản mới)
            try:
                client = GoogleAdsClient.load_from_dict(credentials)
                client.get_service("GoogleAdsService")
                _logger.info("Đã kết nối Google Ads API (Tự động nhận diện phiên bản)")
                return client
            except Exception:
                _logger.info("Không thể tự nhận diện phiên bản, thử chế độ thủ công...")

            # 2. Fallback: Thủ công tìm phiên bản API khả dụng (v18, v17, v16, v15, v14...)
            available_versions = ["v18", "v17", "v16", "v15", "v14"]
            client = None
            last_error = None
            
            for version in available_versions:
                try:
                    client = GoogleAdsClient.load_from_dict(credentials, version=version)
                    client.get_service("GoogleAdsService")
                    _logger.info("Đã kết nối Google Ads API phiên bản: %s", version)
                    return client
                except Exception as e:
                    last_error = e
                    continue
            
            if not client and last_error:
                raise last_error
                
            return client
        except Exception as e:
            raise UserError(_("Không thể khởi tạo Google Ads Client. Chi tiết lỗi: %s") % str(e))

    def action_generate_auth_url(self):
        """Tạo URL Đăng nhập Google để lấy Refresh Token tự động."""
        self.ensure_one()
        if not self.client_id or not self.client_secret:
            raise UserError(_('Vui lòng nhập Client ID và Client Secret trước khi Xác thực!'))
            
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        redirect_uri = f"{base_url}/google_ads/auth_callback"
        
        # Scope cần thiết cho Google Ads API
        scopes = ['https://www.googleapis.com/auth/adwords']
        
        auth_url = 'https://accounts.google.com/o/oauth2/v2/auth'
        params = {
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(scopes),
            'access_type': 'offline',
            'prompt': 'consent',  # Buộc Google sinh ra refresh token
            'state': str(self.id), # Gửi kèm ID để callback biết lưu vào tài khoản nào
        }
        
        url = f"{auth_url}?{urlencode(params)}"
        
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'self',
        }

    def action_test_service_account(self):
        """Kiểm tra tính hợp lệ của Service Account JSON"""
        self.ensure_one()
        if not self.service_account_json:
            raise UserError(_('Chưa có dữ liệu JSON để kiểm tra!'))
            
        try:
            data = json.loads(self.service_account_json)
            if data.get('type') != 'service_account':
                raise UserError(_('File JSON không phải là loại Service Account! (Thiếu type: service_account)'))
            if not data.get('client_email'):
                raise UserError(_('File JSON thiếu trường client_email quan trọng!'))
            if not data.get('private_key'):
                raise UserError(_('File JSON thiếu trường private_key quan trọng!'))
                
            self.message_post(body=Markup(_("<b>Kiểm tra JSON:</b> Thành công! <br/>Tài khoản Service: <code>%s</code>") % data.get('client_email')))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('JSON Hợp lệ'),
                    'message': _('Cấu trúc file JSON Service Account đã đúng.'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except json.JSONDecodeError as e:
            raise UserError(_('Chuỗi JSON không hợp lệ. Vui lòng kiểm tra lại cú pháp (dấu ngoặc, nháy kép).\nLỗi: %s') % str(e))
        except Exception as e:
            raise UserError(_('Đã có lỗi xảy ra: %s') % str(e))

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
        _logger.info("Bắt đầu kiểm tra kết nối Google Ads thật...")
        client = self._get_google_ads_client()
        
        # Lấy thông tin tài khoản để kiểm tra
        # Thay vì dùng CustomerService (có thể thay đổi), dùng GoogleAdsService để truy vấn
        ga_service = client.get_service("GoogleAdsService")
        query = f"SELECT customer.id, customer.descriptive_name FROM customer WHERE customer.id = '{self.operating_customer_id}'"
        
        _logger.info("Executing GoogleAdsService.search on customer_id: %s", self.operating_customer_id)
        _logger.info("Query: %s", query)
        
        try:
            # Thử gọi một query đơn giản nhất
            response = ga_service.search(customer_id=self.operating_customer_id, query=query)
            descriptive_name = "Tài khoản Google Ads"
            for row in response:
                descriptive_name = row.customer.descriptive_name
                break
                
            self.state = 'connected'
            self.message_post(body=_("Kết nối thành công! Đã kết nối với tài khoản: %s") % descriptive_name)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Thành Công'),
                    'message': _('Kết nối thành công tới tài khoản: %s') % descriptive_name,
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            error_msg = str(e)
            _logger.warning("Lỗi Test Connection: %s", error_msg)
            
            hint = ""
            if "USER_PERMISSION_DENIED" in error_msg or "PERMISSION_DENIED" in error_msg:
                # Trích xuất request_id nếú có
                import re
                request_id_match = re.search(r'request_id:\s*"([^"]+)"', error_msg)
                req_id_str = f" (Request ID: {request_id_match.group(1)})" if request_id_match else ""
                
                hint = _("\n\n💡 GỢI Ý KHẮC PHỤC:\n"
                         "1. XÓA TRẮNG ô 'Login Customer ID (MCC)' nếu bạn không chắc chắn tài khoản này thuộc MCC nào.\n"
                         "2. Đảm bảo email bạn vừa dùng để xác thực có quyền truy cập vào tài khoản ID: %s.\n"
                         "3. Nếu bạn truy cập tài khoản con thông qua MCC, hãy chắc chắn ID MCC được điền đúng vào ô 'Login Customer ID'.\n"
                         "4. Bạn có thể dùng tính năng 'Kiểm tra quyền truy cập' trong menu Action của bản ghi này để xem danh sách các ID bạn thực sự có quyền.") % (self.operating_customer_id)
            
            self.state = 'error'
            raise UserError(_("Không thể kết nối Google Ads: %s%s") % (error_msg, hint))

    def action_list_accessible_customers(self):
        """Diagnostic: Liệt kê tất cả Customer ID mà Refresh Token này có quyền thấy."""
        self.ensure_one()
        client = self._get_google_ads_client()
        customer_service = client.get_service("CustomerService")
        
        try:
            accessible_customers = customer_service.list_accessible_customers()
            resource_names = accessible_customers.resource_names
            
            # resource_names có dạng "customers/1234567890"
            ids = [name.split('/')[-1] for name in resource_names]
            
            msg = _("Danh sách Customer IDs mà tài khoản Google của bạn có quyền truy cập:\n\n%s\n\n"
                  "LƯU Ý:\n"
                  "- Nếu Operating ID (%s) KHÔNG có trong danh sách này, nghĩa là email Oauth của bạn không có quyền xem nó.\n"
                  "- Nếu có danh sách ID, hãy thử dùng các ID này làm 'Login Customer ID' nếu tài khoản Operating nằm bên dưới chúng.") % ("\n".join(ids), self.operating_customer_id)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Danh mục ID khả dụng'),
                    'message': msg,
                    'sticky': True,
                    'type': 'info',
                }
            }
        except Exception as e:
            raise UserError(_("Không thể liệt kê tài khoản: %s") % str(e))

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
        
        # Lấy toàn bộ chiến dịch (trừ những cái đã xóa hoàn toàn)
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
            WHERE campaign.status != 'REMOVED'
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
            WHERE ad_group.status != 'REMOVED'
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
            WHERE ad_group_ad.status != 'REMOVED'
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

    @api.model
    def cron_fetch_adsroid_insights(self):
        """Cron job: Lấy insight cho các chiến dịch tự động mỗi ngày"""
        accounts = self.search([('use_adsroid', '=', True), ('state', '=', 'connected')])
        for account in accounts:
            # Lấy các chiến dịch active trong account này
            active_campaigns = account.campaign_ids.filtered(lambda c: c.status == 'enabled')
            for camp in active_campaigns:
                try:
                    camp.action_ask_adsroid(is_cron=True)
                except Exception as e:
                    _logger.error("Lỗi khi fetch adsroid insight cho chiến dịch %s: %s", camp.id, str(e))
