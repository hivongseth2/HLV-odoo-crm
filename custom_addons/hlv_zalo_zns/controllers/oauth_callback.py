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
