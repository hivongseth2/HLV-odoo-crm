from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

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
    
    # API Credentials
    developer_token = fields.Char(string='Developer Token', required=True, tracking=True)
    client_id = fields.Char(string='Client ID', required=True)
    client_secret = fields.Char(string='Client Secret', required=True)
    refresh_token = fields.Char(string='Refresh Token', required=True)
    login_customer_id = fields.Char(
        string='Login Customer ID (MCC)', 
        help='ID của tài khoản người quản lý (MCC). Định dạng: 1234567890 (không có dấu -)'
    )
    operating_customer_id = fields.Char(
        string='Operating Customer ID', required=True,
        help='ID của tài khoản Ads bạn muốn quản lý trực tiếp. Định dạng: 1234567890 (không có dấu -)'
    )

    is_demo = fields.Boolean(string='Chế Độ Demo', default=False, help='Bật để test không cần tài khoản thật')

    state = fields.Selection([
        ('draft', 'Nháp'),
        ('connected', 'Đã Kết Nối'),
        ('error', 'Lỗi')
    ], string='Trạng Thái', default='draft', tracking=True)

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
        if self.is_demo:
            self.state = 'connected'
            self.message_post(body=_("DEMO: Kết nối thành công (Giả lập)"))
            return True
        
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
        self.action_sync_campaigns()
        self.action_sync_ad_groups()
        self.action_sync_ads()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đồng bộ Hoàn tất'),
                'message': _('Đã yêu cầu đồng bộ toàn bộ dữ liệu (Chiến dịch, Nhóm QC, Quảng Cáo, Chỉ số).'),
                'type': 'success',
                'sticky': False,
            }
        }

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

    # ─────────────────────────────────────────────
    # Mock Data for Testing
    # ─────────────────────────────────────────────
    def action_generate_demo_data(self):
        """Tạo dữ liệu giả lập để test rules"""
        self.ensure_one()
        if not self.is_demo:
            raise UserError(_("Chỉ có thể tạo dữ liệu giả ở chế độ Demo."))

        import random
        Campaign = self.env['google.ads.campaign']
        
        # Tạo 3 chiến dịch giả lập
        demo_campaigns = [
            ('Campaign Giày Chạy Bộ - Search', 'SEARCH'),
            ('Campaign Giày Tây - PMax', 'PERFORMANCE_MAX'),
            ('Campaign Sale Xả Kho - Search', 'SEARCH'),
        ]

        for name, ctype in demo_campaigns:
            google_id = str(random.randint(1000000, 9999999))
            vals = {
                'name': name,
                'account_id': self.id,
                'google_campaign_id': google_id,
                'status': 'enabled',
                'channel_type': ctype,
                'clicks': random.randint(500, 2000),
                'impressions': random.randint(10000, 50000),
                'cost': random.uniform(500.0, 5000.0),
                'conversions': random.uniform(5.0, 50.0),
            }
            existing = Campaign.search([('google_campaign_id', '=', google_id)], limit=1)
            if existing:
                existing.write(vals)
            else:
                Campaign.create(vals)
        
        self.state = 'connected'
        self.message_post(body=_("Đã tạo 3 chiến dịch giả lập để chạy thử Rules."))
        return True
