import logging
from datetime import timedelta
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ZaloZNSConfig(models.Model):
    _name = 'hlv.zalo.zns'
    _description = 'Zalo ZNS Config'

    name = fields.Char(default='Zalo ZNS Config')
    app_id = fields.Char('App ID', required=True)
    app_secret = fields.Char('App Secret', required=True)
    oa_id = fields.Char('OA ID', help='Official Account ID')
    callback_url = fields.Char('OAuth Callback URL', required=True)
    access_token = fields.Text('Access Token', readonly=True)
    refresh_token = fields.Text('Refresh Token', readonly=True)
    token_expires_at = fields.Datetime('Token Expires At', readonly=True)
    template_id = fields.Char('ZNS Template ID', help='Approved ZNS template ID')

    authorize_url = fields.Char('Authorize URL', compute='_compute_authorize_url', readonly=True)

    @api.depends('app_id', 'callback_url')
    def _compute_authorize_url(self):
        for rec in self:
            if rec.app_id and rec.callback_url:
                # Common OA permission URL pattern (adjust if your app requires different scopes/params)
                from urllib.parse import quote
                rec.authorize_url = (
                    "https://oauth.zaloapp.com/v4/oa/permission"
                    f"?app_id={rec.app_id}&redirect_uri={quote(rec.callback_url, safe='')}"
                    "&state=odoo_zns"
                )
            else:
                rec.authorize_url = False

    def action_open_oauth(self):
        self.ensure_one()
        if not self.authorize_url:
            raise UserError(_("Missing app_id or callback_url"))
        return {
            "type": "ir.actions.act_url",
            "target": "new",
            "url": self.authorize_url,
        }

    # ---- Token helpers ----
    def _token_expired(self):
        return (not self.token_expires_at) or (fields.Datetime.now() >= self.token_expires_at)

    def request_access_token_with_code(self, code, code_verifier=None):
        self.ensure_one()
        endpoint = 'https://oauth.zaloapp.com/v4/oa/access_token'
        data = {
            'grant_type': 'authorization_code',
            'app_id': self.app_id,
            'code': code,
            # 'redirect_uri': self.callback_url,  # Bật dòng này nếu Zalo yêu cầu so khớp redirect_uri
        }
        if code_verifier:
            data['code_verifier'] = code_verifier

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'secret_key': self.app_secret,   # QUAN TRỌNG cho v4
        }

        r = requests.post(endpoint, data=data, headers=headers, timeout=15)
        r.raise_for_status()
        j = r.json()

        access = j.get('access_token')
        refresh = j.get('refresh_token')
        if not access:
            # Log để dễ debug nếu Zalo trả lỗi dạng khác
            _logger.error("Zalo token exchange response: %s", r.text)
            raise UserError(_("Failed to get access_token from Zalo."))

        self.write({
            "access_token": access,
            "refresh_token": refresh,
            "token_expires_at": fields.Datetime.now() + timedelta(seconds=int(j.get("expires_in", 3600)) - 60),
        })
        _logger.info("Zalo access token stored (expires_in=%s)", j.get("expires_in"))
        return j


    def refresh_access_token(self):
        for rec in self:
            if not rec.refresh_token:
                continue
            try:
                endpoint = 'https://oauth.zaloapp.com/v4/oa/access_token'
                data = {
                    'grant_type': 'refresh_token',
                    'app_id': rec.app_id,
                    'refresh_token': rec.refresh_token,
                }
                headers = {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'secret_key': rec.app_secret,  # QUAN TRỌNG
                }
                r = requests.post(endpoint, data=data, headers=headers, timeout=15)
                r.raise_for_status()
                j = r.json()
                access = j.get('access_token')
                if not access:
                    _logger.error("Zalo refresh response: %s", r.text)
                    continue
                rec.write({
                    "access_token": access,
                    "refresh_token": j.get("refresh_token", rec.refresh_token),
                    "token_expires_at": fields.Datetime.now() + timedelta(seconds=int(j.get("expires_in", 3600)) - 60),
                })
                _logger.info("Zalo access token refreshed")
            except Exception as e:
                _logger.exception("Refresh Zalo token failed: %s", e)


    # ---- Sending ZNS ----
    def send_zns(self, msisdn, params):
        """Send a ZNS message using the approved template.
        NOTE: Adjust endpoint and payload to match Zalo's latest ZNS API.
        """
        self.ensure_one()
        if (not self.access_token) or self._token_expired():
            self.refresh_access_token()
        if not self.access_token:
            raise UserError(_("No valid access token"))

        # Example endpoint (adjust to actual ZNS send endpoint if different)
        endpoint = "https://openapi.zalo.me/v2.0/oa/message"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "template_id": self.template_id,
            "to": msisdn,
            "params": params or {},
        }
        r = requests.post(endpoint, headers=headers, json=body, timeout=20)
        if r.status_code >= 400:
            _logger.error("ZNS send failed %s: %s", r.status_code, r.text)
            r.raise_for_status()
        _logger.info("ZNS sent to %s; response=%s", msisdn, r.text)
        return r.json()
