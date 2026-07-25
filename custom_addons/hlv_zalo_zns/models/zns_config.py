# models/zns_config.py
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
    
    # ===== NEW: Option to use Shared Token =====
    use_shared_token = fields.Boolean(
        'Use Shared Token',
        default=True,
        help='Nếu bật, sẽ sử dụng token từ Shared Token Manager thay vì token riêng'
    )
    
    # ===== OLD: Deprecated token fields (kept for backward compatibility) =====
    app_id = fields.Char('App ID', help='[DEPRECATED] Sử dụng Shared Token Manager thay thế')
    app_secret = fields.Char('App Secret', help='[DEPRECATED] Sử dụng Shared Token Manager thay thế')
    oa_id = fields.Char('OA ID', help='Official Account ID')
    callback_url = fields.Char('OAuth Callback URL', help='[DEPRECATED] Sử dụng Shared Token Manager thay thế')
    access_token = fields.Text('Access Token', readonly=True, help='[DEPRECATED] Sử dụng Shared Token Manager thay thế')
    refresh_token = fields.Text('Refresh Token', readonly=True, help='[DEPRECATED] Sử dụng Shared Token Manager thay thế')
    token_expires_at = fields.Datetime('Token Expires At', readonly=True, help='[DEPRECATED] Sử dụng Shared Token Manager thay thế')
    template_id = fields.Char('ZNS Template ID', help='Approved ZNS template ID')
    wp_template_id = fields.Char(
            'ZNS Template ID cho đơn WordPress',
            help='Template ZNS dùng để xác nhận đơn hàng từ WordPress (khác với template giao hàng nếu cần)'
        )
    authorize_url = fields.Char('Authorize URL', compute='_compute_authorize_url', readonly=True)




    # -------------------- OAuth permission URL --------------------
    @api.depends('app_id', 'callback_url')
    def _compute_authorize_url(self):
        for rec in self:
            if rec.app_id and rec.callback_url:
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
        return {"type": "ir.actions.act_url", "target": "new", "url": self.authorize_url}

    # -------------------- Token helpers --------------------
    def _token_expired(self):
        return (not self.token_expires_at) or (fields.Datetime.now() >= self.token_expires_at)

    def request_access_token_with_code(self, code, code_verifier=None):
        """Exchange code -> access_token (OAuth v4 for OA)."""
        self.ensure_one()
        endpoint = 'https://oauth.zaloapp.com/v4/oa/access_token'
        data = {
            'grant_type': 'authorization_code',
            'app_id': self.app_id,
            'code': code,
            # 'redirect_uri': self.callback_url,  # mở nếu Zalo yêu cầu
        }
        if code_verifier:
            data['code_verifier'] = code_verifier

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'secret_key': self.app_secret,  # v4: dùng header này
        }

        r = requests.post(endpoint, data=data, headers=headers, timeout=15)
        r.raise_for_status()
        j = r.json()

        access = j.get('access_token')
        refresh = j.get('refresh_token')
        if not access:
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
        """Refresh access token using refresh_token."""
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
                    'secret_key': rec.app_secret,
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

    def _get_access_token(self):
        """
        Lấy access token - Ưu tiên từ Shared Token Manager
        
        :return: access_token (string) hoặc False
        """
        self.ensure_one()
        
        if self.use_shared_token:
            # Sử dụng Shared Token Manager
            _logger.debug("ZNS Config: Using Shared Token Manager")
            access_token = self.env['hlv.zalo.shared.token']._get_shared_token()
            if access_token:
                return access_token
            else:
                _logger.warning("ZNS Config: Shared Token not available, falling back to own token")
        
        # Fallback: Sử dụng token riêng (backward compatibility)
        if (not self.access_token) or self._token_expired():
            self.refresh_access_token()
        
        return self.access_token

    # -------------------- Send ZNS --------------------
    def send_zns(self, msisdn, params,template_id_override=None):
        """
        Gửi ZNS theo template:
        - Header dùng 'access_token'
        - Body dùng 'phone' + 'template_data'
        - Xử lý một số lỗi phổ biến: token invalid, price invalid format
        - Hỗ trợ Shared Token (use_shared_token)
        """
        self.ensure_one()

        def _call(body, token):
            endpoint = "https://business.openapi.zalo.me/message/template"
            headers = {
                "Content-Type": "application/json",
                "access_token": token,
            }
            r = requests.post(endpoint, json=body, headers=headers, timeout=20)
            txt = r.text
            try:
                j = r.json()
            except Exception:
                j = {"raw": txt}
            _logger.info("ZNS call status=%s resp=%s", r.status_code, txt)
            return r.status_code, j

        # Lấy access token (từ Shared Token hoặc token riêng)
        access_token = self._get_access_token()
        if not access_token:
            raise UserError(_("No valid access token. Please configure Shared Token Manager or own token."))


        template_id = template_id_override or self.template_id
        if not template_id:
            raise UserError(_("Missing ZNS template ID"))
        body = {
            # "template_id": self.template_id,
            "template_id":template_id ,

            "phone": msisdn,
            "template_data": params,
            # "oa_id": self.oa_id,  # mở nếu cần
        }

        status, resp = _call(body, access_token)

        # Nếu token invalid (-124/-216), thử refresh rồi gọi lại 1 lần
        if isinstance(resp, dict) and resp.get("error") in (-124, -216):
            _logger.info("ZNS token invalid -> refresh and retry once")
            
            if self.use_shared_token:
                # Refresh Shared Token
                token_manager = self.env['hlv.zalo.shared.token'].search([('active', '=', True)], limit=1)
                if token_manager:
                    token_manager.refresh_access_token()
                    access_token = token_manager.access_token
            else:
                # Refresh own token
                self.refresh_access_token()
                access_token = self.access_token
            
            if not access_token:
                raise UserError(_("Cannot refresh access token"))
            status, resp = _call(body, access_token)

        # Nếu price invalid format (-1124), ép về chuỗi số và retry 1 lần
        if isinstance(resp, dict) and resp.get("error") == -1124:
            td = body["template_data"].copy()
            if "price" in td:
                td["price"] = str(td["price"])  # ép chuỗi số
                body["template_data"] = td
                _logger.info("ZNS retry with price as string")
                status, resp = _call(body, access_token)

        return resp
