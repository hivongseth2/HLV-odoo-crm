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

    @http.route(['/hlv_zalo/shared/oauth/callback'], type='http', auth='public', csrf=False)
    def shared_token_oauth_callback(self, **kwargs):
        """Callback cho Shared Token OAuth"""
        code = kwargs.get('code')
        state = kwargs.get('state')
        if not code:
            return "Missing authorization code"
        try:
            token_manager = request.env['hlv.zalo.shared.token'].sudo().search([('active', '=', True)], limit=1)
            if not token_manager:
                return "❌ Shared Token Manager not found. Please create one first."
            token_manager.sudo().request_access_token_with_code(code)
            return """
                <html>
                <head>
                    <title>Zalo Authorization Success</title>
                    <style>
                        body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
                        .success { color: #28a745; font-size: 48px; }
                        .message { font-size: 20px; margin: 20px 0; }
                        .info { color: #666; font-size: 14px; }
                    </style>
                </head>
                <body>
                    <div class="success">✅</div>
                    <div class="message">Authorization Successful!</div>
                    <div class="info">
                        Token has been stored in Shared Token Manager.<br/>
                        You can close this window and refresh the page.
                    </div>
                </body>
                </html>
            """
        except Exception as e:
            _logger.exception("Shared Token OAuth token exchange failed: %s", e)
            return "❌ Authorization failed: %s" % e
