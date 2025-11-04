import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class HLVZaloOAuth(http.Controller):

    @http.route(['/hlv_zalo/oauth/callback'], type='http', auth='public', csrf=False)
    def oauth_callback(self, **kwargs):
        code = kwargs.get('code')
        state = kwargs.get('state')
        if not code:
            return "Missing code"
        config = request.env['hlv.zalo.zns'].sudo().search([], limit=1)
        if not config:
            return "Config not found"
        try:
            config.sudo().request_access_token_with_code(code)
        except Exception as e:
            _logger.exception("Zalo token exchange failed: %s", e)
            return "Token exchange failed: %s" % e
        return "OK - token stored. You can close this window."

    @http.route(['/hlv_zalo/stock_notification/oauth/callback'], type='http', auth='public', csrf=False)
    def stock_notification_oauth_callback(self, **kwargs):
        """Callback cho Stock Notification OAuth"""
        code = kwargs.get('code')
        state = kwargs.get('state')
        if not code:
            return "Missing authorization code"
        try:
            config = request.env['hlv.zalo.stock.notification'].sudo().search([('active', '=', True)], limit=1)
            if not config:
                return "Stock Notification config not found"
            config.sudo().request_access_token_with_code(code)
            return "✅ Authorization successful! Token stored. You can close this window and refresh the page."
        except Exception as e:
            _logger.exception("Stock Notification OAuth token exchange failed: %s", e)
            return "❌ Authorization failed: %s" % e
