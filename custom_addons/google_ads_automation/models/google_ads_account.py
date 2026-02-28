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
    _description = 'Google Ads API Account'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Account Name', required=True)
    active = fields.Boolean(default=True)
    
    # API Credentials
    developer_token = fields.Char(string='Developer Token', required=True, tracking=True)
    client_id = fields.Char(string='Client ID', required=True)
    client_secret = fields.Char(string='Client Secret', required=True)
    refresh_token = fields.Char(string='Refresh Token', required=True)
    login_customer_id = fields.Char(
        string='Login Customer ID (MCC)', 
        help='The Manager Account ID to authenticate. Format: 1234567890 (no dashes)'
    )
    operating_customer_id = fields.Char(
        string='Operating Customer ID', required=True,
        help='The ID of the specific Ads Account you want to manage. Format: 1234567890 (no dashes)'
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('connected', 'Connected'),
        ('error', 'Error')
    ], string='Status', default='draft', tracking=True)

    def _get_google_ads_client(self):
        """Build Google Ads Client from credentials"""
        self.ensure_one()
        if not GoogleAdsClient:
            raise UserError(_("The 'google-ads' python library is not installed. Please contact your system administrator."))
        
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
            raise UserError(_("Could not construct Google Ads Client. Error: %s") % str(e))

    def action_test_connection(self):
        self.ensure_one()
        client = self._get_google_ads_client()
        customer_service = client.get_service("CustomerService")
        
        # We try to load a customer to verify credentials. We will use the operating_customer_id.
        resource_name = customer_service.customer_path(self.operating_customer_id)
        
        try:
            response = customer_service.get_customer(resource_name=resource_name)
            self.state = 'connected'
            self.message_post(body=_("Connection successful! Connected to account: %s") % response.descriptive_name)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Connection successful to account: %s') % response.descriptive_name,
                    'type': 'success',
                    'sticky': False,
                }
            }
        except GoogleAdsException as ex:
            error_details = []
            for error in ex.failure.errors:
                error_details.append(f"{error.error_code}: {error.message}")
            self.state = 'error'
            raise UserError(_("Google Ads API Error: \n%s") % '\n'.join(error_details))
        except Exception as e:
            self.state = 'error'
            raise UserError(_("Connection failed: %s") % str(e))

    def action_sync_campaigns(self):
        self.ensure_one()
        client = self._get_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")
        
        query = """
            SELECT
              campaign.id,
              campaign.name,
              campaign.status,
              campaign.advertising_channel_type
            FROM campaign
            ORDER BY campaign.id
        """
        
        try:
            stream = ga_service.search_stream(customer_id=self.operating_customer_id, query=query)
            
            campaign_obj = self.env['google.ads.campaign']
            synced_count = 0
            for batch in stream:
                for row in batch.results:
                    campaign = row.campaign
                    
                    status_name = campaign.status.name.lower() # UNKNOWN, UNSPECIFIED, ENABLED, PAUSED, REMOVED
                    
                    vals = {
                        'name': campaign.name,
                        'account_id': self.id,
                        'google_campaign_id': str(campaign.id),
                        'status': status_name,
                        'channel_type': campaign.advertising_channel_type.name,
                    }
                    
                    existing = campaign_obj.search([('google_campaign_id', '=', str(campaign.id))], limit=1)
                    if existing:
                        existing.write(vals)
                    else:
                        campaign_obj.create(vals)
                    synced_count += 1
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sync Complete'),
                    'message': _('Successfully synced %s campaigns.') % synced_count,
                    'type': 'success',
                    'sticky': False,
                }
            }
            
        except GoogleAdsException as ex:
            raise UserError(_("Could not fetch campaigns. Google API Error: %s") % str(ex))
