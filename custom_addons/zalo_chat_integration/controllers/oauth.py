# -*- coding: utf-8 -*-

import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class ZaloOAuthController(http.Controller):
    """Controller to handle Zalo OAuth2 callbacks"""

    @http.route('/zalo/oauth/callback', type='http', auth='public', csrf=False)
    def zalo_oauth_callback(self, **kwargs):
        """
        Handle OAuth2 callback from Zalo
        
        Expected params:
        - code: Authorization code
        - oa_id: Official Account ID (optional)
        """
        code = kwargs.get('code')
        
        if not code:
            return request.render('zalo_chat_integration.zalo_auth_error', {
                'error': 'No authorization code received',
            })
        
        try:
            # Get the first active config (or create if needed)
            Config = request.env['zalo.oa.config'].sudo()
            config = Config.search([('active', '=', True)], limit=1)
            
            if not config:
                return request.render('zalo_chat_integration.zalo_auth_error', {
                    'error': 'No active Zalo OA configuration found. Please create one first.',
                })
            
            # Exchange code for token
            config.exchange_code_for_token(code)
            
            return request.render('zalo_chat_integration.zalo_auth_success', {
                'config': config,
            })
            
        except Exception as e:
            _logger.error(f'OAuth callback error: {str(e)}', exc_info=True)
            return request.render('zalo_chat_integration.zalo_auth_error', {
                'error': str(e),
            })
