from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class WordPressConfig(models.Model):
    _name = 'wordpress.config'
    _description = 'WordPress Configuration'
    _rec_name = 'name'

    name = fields.Char(
        string='Config Name',
        required=True,
        help='Name for this WordPress configuration (e.g., Main Store)'
    )

    wc_domain = fields.Char(
        string='WordPress Domain',
        required=True,
        help='Domain of WordPress store (e.g., https://hoanglongvu.com - WITHOUT trailing slash)',
        placeholder='https://hoanglongvu.com'
    )

    wc_key = fields.Char(
        string='Consumer Key',
        required=True,
        help='WooCommerce REST API Consumer Key'
    )

    wc_secret = fields.Char(
        string='Consumer Secret',
        required=True,
        help='WooCommerce REST API Consumer Secret'
    )

    cache_purge_url = fields.Char(
        string='Cache Purge URL',
        help='LiteSpeed cache purge endpoint (optional)',
        placeholder='/wp-json/litespeed/v1/purge?type=product&sku='
    )

    sync_log_days = fields.Integer(
        string='Keep Sync Logs (Days)',
        default=30,
        help='Number of days to keep sync logs'
    )

    last_sync_date = fields.Datetime(
        string='Last Sync Date',
        readonly=True
    )

    active = fields.Boolean(
        string='Active',
        default=True
    )

    @api.constrains('wc_domain')
    def _check_domain(self):
        """Ensure domain format is correct"""
        for record in self:
            if record.wc_domain and record.wc_domain.endswith('/'):
                raise ValueError('Domain should NOT have trailing slash (e.g., https://hoanglongvu.com)')

    def test_connection(self):
        """Test WordPress API connection"""
        self.ensure_one()

        try:
            from requests.auth import HTTPBasicAuth
            import requests

            # Simple API call to test connection
            url = f"{self.wc_domain}/wp-json/wc/v3/products?per_page=1"
            auth = HTTPBasicAuth(self.wc_key, self.wc_secret)

            response = requests.get(url, auth=auth, timeout=10)

            if response.status_code == 200:
                _logger.info(f"✅ WordPress connection test successful for {self.name}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': '✅ Connection Successful',
                        'message': f'WordPress API connection test passed',
                        'type': 'success',
                    }
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                _logger.error(f"❌ WordPress connection test failed: {error_msg}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': '❌ Connection Failed',
                        'message': error_msg,
                        'type': 'danger',
                    }
                }
        except Exception as e:
            _logger.error(f"❌ Error testing WordPress connection: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '❌ Error',
                    'message': str(e),
                    'type': 'danger',
                }
            }
