import json
import logging
import requests
from markupsafe import Markup

from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)

class GoogleAdsAuthController(http.Controller):

    @http.route('/google_ads/auth_callback', type='http', auth='user', website=False)
    def google_ads_auth_callback(self, **kwargs):
        """
        Endpoint Callback để nhận Authorization Code từ Google sau khi người dùng đồng ý cấp quyền.
        Trao đổi Auth Code lấy Refresh Token.
        """
        code = kwargs.get('code')
        error = kwargs.get('error')
        state = kwargs.get('state')  # account_id được truyền qua state

        if error:
            _logger.error("OAuth callback returned error: %s", error)
            return request.render('http_routing.http_error', {
                'status_code': 400,
                'status_message': _('Xác thực thất bại từ Google: %s' % error),
            })

        if not code or not state:
            return request.render('http_routing.http_error', {
                'status_code': 400,
                'status_message': _('Thiếu tham số code hoặc state (account_id) trong callback.'),
            })

        try:
            account_id = int(state)
            account = request.env['google.ads.account'].sudo().browse(account_id)
            if not account.exists():
                return request.render('http_routing.http_error', {
                    'status_code': 404,
                    'status_message': _('Không tìm thấy tài khoản Google Ads có ID: %s' % account_id),
                })

            if not account.client_id or not account.client_secret:
                return request.render('http_routing.http_error', {
                    'status_code': 400,
                    'status_message': _('Tài khoản chưa được cấu hình Client ID / Client Secret.'),
                })

            # URL Gọi từ đâu thì tạo Redirect URI về đúng đó
            base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
            redirect_uri = f"{base_url}/google_ads/auth_callback"

            # Đổi Code lấy Refresh Token
            token_url = "https://oauth2.googleapis.com/token"
            payload = {
                'code': code,
                'client_id': account.client_id,
                'client_secret': account.client_secret,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code',
            }

            response = requests.post(token_url, data=payload)
            response.raise_for_status()
            
            data = response.json()
            refresh_token = data.get('refresh_token')
            
            if refresh_token:
                account.write({'refresh_token': refresh_token})
                account.message_post(body=Markup(_("<b>Xác thực OAuth 2.0 thành công!</b> Đã cấp phát Refresh Token mới tự động.")))
            else:
                _logger.warning("No refresh_token returned in Google response: %s", data)
                account.message_post(body=Markup(_("<b>Oauth Warning:</b> Google xác thực thành công nhưng không trả về refresh_token. Hãy chắc chắn bạn đang dùng prompt=consent hoặc kiểm tra Google Cloud.")))

            # Redirect về Form Tài khoản
            action = request.env.ref('google_ads_automation.action_google_ads_account').id
            return request.redirect(f'/web#id={account.id}&view_type=form&model=google.ads.account&action={action}')

        except Exception as e:
            _logger.exception("Lỗi xử lý OAuth Callback Google Ads: %s", str(e))
            return request.render('http_routing.http_error', {
                'status_code': 500,
                'status_message': _('Có lỗi xảy ra trong quá trình đổi Auth Code: %s' % str(e)),
            })
