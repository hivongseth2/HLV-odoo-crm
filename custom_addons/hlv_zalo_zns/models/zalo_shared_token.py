# models/zalo_shared_token.py
import logging
import requests
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ZaloSharedToken(models.Model):
    """
    Shared Token Manager cho tất cả các chức năng Zalo
    
    === MỤC ĐÍCH ===
    - Quản lý tập trung access_token và refresh_token cho 1 Zalo OA
    - Tránh việc lưu trữ token ở nhiều nơi
    - Đồng bộ token giữa ZNS (gửi khách hàng) và Stock Notification (gửi nội bộ)
    
    === CÁCH SỬ DỤNG ===
    
    1. Tạo 1 bản ghi duy nhất với:
       - App ID, Secret Key từ Zalo Developer Portal
       - Callback URL để nhận OAuth callback
       - Active = True
    
    2. Click "Authorize with Zalo" để lấy token lần đầu
    
    3. Các module khác (ZNS, Stock Notification) sẽ:
       - Gọi _get_shared_token() để lấy access_token
       - Không cần lưu token riêng nữa
       - Token tự động refresh khi hết hạn
    
    === LƯU Ý ===
    - Chỉ nên có 1 bản ghi active tại một thời điểm
    - Token được refresh tự động bởi cron job mỗi giờ
    - On-demand refresh khi phát hiện token hết hạn
    """
    
    _name = 'hlv.zalo.shared.token'
    _description = 'Zalo Shared Token Manager'
    _rec_name = 'name'

    name = fields.Char('Name', default='Zalo OA Token', required=True)
    app_id = fields.Char('App ID', required=True, help='Lấy từ Zalo Developer Portal')
    secret_key = fields.Char('Secret Key', required=True, help='Lấy từ Zalo Developer Portal')
    callback_url = fields.Char(
        'OAuth Callback URL', 
        required=True, 
        default='https://your-odoo-domain.com/hlv_zalo/shared/oauth/callback',
        help='URL để Zalo redirect sau khi authorize'
    )
    
    # Token fields
    refresh_token = fields.Text('Refresh Token', help='Token dùng để refresh access token')
    access_token = fields.Text('Access Token', readonly=True, help='Token dùng để gọi API')
    token_expires_at = fields.Datetime('Token Expires At', readonly=True)
    
    # Computed field
    authorize_url = fields.Char('Authorize URL', compute='_compute_authorize_url', readonly=True)
    token_status = fields.Char('Token Status', compute='_compute_token_status', readonly=True)
    
    active = fields.Boolean('Active', default=True)
    
    # Statistics
    last_refresh_date = fields.Datetime('Last Refresh Date', readonly=True)
    refresh_count = fields.Integer('Refresh Count', readonly=True, default=0)
    
    _sql_constraints = [
        ('app_id_unique', 'unique(app_id)', 'App ID must be unique!'),
    ]

    @api.depends('app_id', 'callback_url')
    def _compute_authorize_url(self):
        """Tính toán URL để authorize với Zalo"""
        for rec in self:
            if rec.app_id and rec.callback_url:
                from urllib.parse import quote
                rec.authorize_url = (
                    "https://oauth.zaloapp.com/v4/oa/permission"
                    f"?app_id={rec.app_id}&redirect_uri={quote(rec.callback_url, safe='')}"
                    "&state=odoo_shared_token"
                )
            else:
                rec.authorize_url = False

    @api.depends('token_expires_at', 'access_token')
    def _compute_token_status(self):
        """Tính toán trạng thái token"""
        for rec in self:
            if not rec.access_token:
                rec.token_status = '❌ No Token'
            elif not rec.token_expires_at:
                rec.token_status = '⚠️ Unknown'
            elif rec._is_token_expired():
                rec.token_status = '⏰ Expired'
            else:
                remaining = rec.token_expires_at - fields.Datetime.now()
                hours = remaining.total_seconds() / 3600
                if hours > 24:
                    rec.token_status = f'✅ Valid ({int(hours/24)} days)'
                else:
                    rec.token_status = f'✅ Valid ({int(hours)} hours)'

    def action_open_oauth(self):
        """Mở URL để authorize với Zalo"""
        self.ensure_one()
        if not self.authorize_url:
            raise UserError(_("Missing app_id or callback_url"))
        return {"type": "ir.actions.act_url", "target": "new", "url": self.authorize_url}

    def request_access_token_with_code(self, code):
        """Exchange authorization code -> access_token & refresh_token"""
        self.ensure_one()
        endpoint = 'https://oauth.zaloapp.com/v4/oa/access_token'
        data = {
            'grant_type': 'authorization_code',
            'app_id': self.app_id,
            'code': code,
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'secret_key': self.secret_key,
        }

        try:
            _logger.info("Zalo Shared Token: Exchanging authorization code for access token...")
            response = requests.post(endpoint, data=data, headers=headers, timeout=15)
            response.raise_for_status()
            result = response.json()

            access_token = result.get('access_token')
            refresh_token = result.get('refresh_token')
            
            if not access_token:
                error_msg = result.get('error_description', 'Unknown error')
                _logger.error("Zalo Shared Token: Failed to get access token: %s", error_msg)
                raise UserError(_("Không thể lấy access token: %s") % error_msg)

            expires_in = int(result.get('expires_in', 3600))
            self.write({
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_expires_at': fields.Datetime.now() + timedelta(seconds=expires_in - 60),
                'last_refresh_date': fields.Datetime.now(),
                'refresh_count': self.refresh_count + 1,
            })
            
            _logger.info("Zalo Shared Token: Tokens obtained successfully (expires_in=%s)", expires_in)
            return result
            
        except requests.exceptions.RequestException as e:
            _logger.exception("Zalo Shared Token: Failed to request access token: %s", e)
            raise UserError(_("Lỗi kết nối Zalo API: %s") % str(e))
        except Exception as e:
            _logger.exception("Zalo Shared Token: Unexpected error requesting access token: %s", e)
            raise UserError(_("Lỗi không mong muốn: %s") % str(e))

    def _is_token_expired(self):
        """Kiểm tra token đã hết hạn chưa"""
        self.ensure_one()
        if not self.token_expires_at:
            return True
        # Thêm buffer 60s để tránh token hết hạn giữa chừng
        return fields.Datetime.now() >= (self.token_expires_at - timedelta(seconds=60))

    def _get_advisory_lock_id(self):
        """Tạo advisory lock ID cho bản ghi này"""
        self.ensure_one()
        return hash(('hlv.zalo.shared.token', self.id)) & 0x7FFFFFFF

    def ensure_valid_token(self):
        """
        On-demand token refresh với advisory lock
        
        :return: True nếu token hợp lệ, False nếu có lỗi
        """
        self.ensure_one()
        
        if not self._is_token_expired():
            return True
        
        _logger.warning("Zalo Shared Token %s: token expired, attempting on-demand refresh", self.id)
        
        try:
            lock_id = self._get_advisory_lock_id()
            
            self.env.cr.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,))
            lock_acquired = self.env.cr.fetchone()[0]
            
            if not lock_acquired:
                _logger.warning(
                    "Zalo Shared Token %s: could not acquire lock, skipping on-demand refresh",
                    self.id
                )
                return False
            
            try:
                _logger.info("Zalo Shared Token %s: acquired lock, starting on-demand refresh", self.id)
                self.refresh_access_token()
                _logger.info("Zalo Shared Token %s: on-demand refresh completed successfully", self.id)
                return True
                
            finally:
                self.env.cr.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
        
        except Exception as e:
            _logger.exception("Zalo Shared Token %s: error during on-demand refresh: %s", self.id, e)
            return False

    def refresh_access_token(self):
        """Refresh access token using refresh_token"""
        for rec in self:
            if not rec.refresh_token:
                _logger.warning("Zalo Shared Token %s: No refresh token", rec.id)
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
                    'secret_key': rec.secret_key,
                }
                
                _logger.info("Zalo Shared Token %s: Refreshing access token...", rec.id)
                response = requests.post(endpoint, data=data, headers=headers, timeout=15)
                response.raise_for_status()
                result = response.json()
                
                access_token = result.get('access_token')
                if not access_token:
                    error_msg = result.get('error_description', result.get('message', 'Unknown error'))
                    _logger.error("Zalo Shared Token %s: Failed to refresh token: %s", rec.id, error_msg)
                    continue
                
                expires_in = int(result.get('expires_in', 3600))
                rec.write({
                    'access_token': access_token,
                    'refresh_token': result.get('refresh_token', rec.refresh_token),
                    'token_expires_at': fields.Datetime.now() + timedelta(seconds=expires_in - 60),
                    'last_refresh_date': fields.Datetime.now(),
                    'refresh_count': rec.refresh_count + 1,
                })
                _logger.info("Zalo Shared Token %s: Access token refreshed successfully", rec.id)
                
            except Exception as e:
                _logger.exception("Zalo Shared Token %s: Failed to refresh access token: %s", rec.id, e)

    @api.model
    def _get_shared_token(self):
        """
        Lấy shared token manager đang active
        Tự động refresh nếu token hết hạn
        
        :return: access_token (string) hoặc False nếu không có
        """
        token_manager = self.search([('active', '=', True)], limit=1)
        
        if not token_manager:
            _logger.error("No active Zalo Shared Token found")
            return False
        
        # On-demand refresh nếu cần
        if token_manager._is_token_expired():
            token_manager.ensure_valid_token()
        
        return token_manager.access_token

    def action_refresh_token(self):
        """Action button để manually refresh token"""
        self.ensure_one()
        try:
            self.refresh_access_token()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Refresh Token'),
                    'message': _('Đã refresh access token thành công'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(_("Lỗi khi refresh token: %s") % str(e))

    def action_test_token(self):
        """Action button để test token"""
        self.ensure_one()
        
        if not self.access_token:
            raise UserError(_("Chưa có access token. Vui lòng authorize trước."))
        
        # Test bằng cách gọi API get profile
        try:
            endpoint = 'https://openapi.zalo.me/v2.0/oa/getoa'
            headers = {
                'access_token': self.access_token
            }
            response = requests.get(endpoint, headers=headers, timeout=10)
            result = response.json()
            
            if result.get('error') == 0:
                oa_name = result.get('data', {}).get('name', 'Unknown')
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Token Valid'),
                        'message': _('Token hợp lệ! OA: %s') % oa_name,
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                error_msg = result.get('message', 'Unknown error')
                raise UserError(_("Token không hợp lệ: %s") % error_msg)
                
        except Exception as e:
            raise UserError(_("Lỗi khi test token: %s") % str(e))
