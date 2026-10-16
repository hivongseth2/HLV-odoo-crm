# models/zalo_shared_token.py
import logging
import psycopg2
import requests
from datetime import timedelta
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
    last_refresh_error = fields.Text(
        'Last Refresh Error', readonly=True,
        help='Lỗi của lần refresh gần nhất (cron chạy ngầm nên lỗi không hiện lên màn hình)'
    )
    
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
                'last_refresh_error': False,
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

    def _request_refreshed_tokens(self):
        """Gọi Zalo đổi refresh_token hiện tại lấy cặp token mới.

        :return: (dict kết quả Zalo, None) khi thành công,
                 (None, chuỗi lỗi kèm mã lỗi Zalo) khi Zalo từ chối hoặc lỗi mạng
        """
        self.ensure_one()
        try:
            response = requests.post(
                'https://oauth.zaloapp.com/v4/oa/access_token',
                data={
                    'grant_type': 'refresh_token',
                    'app_id': self.app_id,
                    'refresh_token': self.refresh_token,
                },
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'secret_key': self.secret_key,
                },
                timeout=15,
            )
            result = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            return None, _("Lỗi kết nối Zalo: %s") % e

        if result.get('access_token'):
            return result, None
        # Zalo trả HTTP 200 kèm {"error": -14014, "error_name": ..., "error_description": ...}
        detail = (result.get('error_description') or result.get('error_reason')
                  or result.get('message') or result.get('error_name') or 'Unknown error')
        return None, "[%s] %s" % (result.get('error', response.status_code), detail)

    def _refresh_in_own_transaction(self, force=False):
        """Đổi refresh_token lấy token mới và COMMIT ngay trên một cursor riêng.

        Vì sao cursor riêng: Zalo xoay vòng refresh_token — gọi refresh xong là token
        cũ chết ngay. Trước đây token mới được ghi trong transaction của nghiệp vụ đang
        chạy (validate phiếu kho, webhook đơn...). Transaction đó rollback (lỗi phía sau,
        serialization retry) là token mới mất, DB giữ token cũ đã chết → mọi lần refresh
        sau đều hỏng cho tới khi authorize lại.

        Transaction ngoài chạy REPEATABLE READ nên không thấy giá trị vừa commit ở đây;
        người gọi phải dùng access_token được trả về, đừng đọc lại field.

        :param force: True để refresh kể cả khi token chưa tới hạn (nút bấm, Zalo báo
                      token sai). False thì bỏ qua nếu tiến trình khác vừa refresh xong.
        :return: access_token mới (hoặc token còn hạn nếu không cần refresh)
        :raise UserError: Zalo từ chối, lỗi mạng, chưa có refresh_token, hoặc dòng đang bị khoá
        """
        self.ensure_one()
        error = None
        try:
            with self.env.registry.cursor() as cr:
                # Khoá dòng để hai tiến trình không cùng tiêu một refresh_token. Có hạn chờ
                # vì nếu chính request ngoài đang giữ dòng (form vừa sửa rồi bấm Refresh)
                # thì chờ vô hạn sẽ treo cả hai.
                cr.execute("SET LOCAL lock_timeout = '20s'")
                cr.execute("SELECT id FROM hlv_zalo_shared_token WHERE id = %s FOR UPDATE", (self.id,))
                rec = self.with_env(self.env(cr=cr))
                if not force and not rec._is_token_expired():
                    return rec.access_token

                if not rec.refresh_token:
                    error = _("Chưa có refresh token, cần Authorize with Zalo")
                else:
                    _logger.info("Zalo Shared Token %s: refreshing access token...", rec.id)
                    result, error = rec._request_refreshed_tokens()

                if error:
                    rec.write({'last_refresh_error': "%s — %s" % (fields.Datetime.now(), error)})
                else:
                    expires_in = int(result.get('expires_in', 3600))
                    rec.write({
                        'access_token': result['access_token'],
                        'refresh_token': result.get('refresh_token', rec.refresh_token),
                        'token_expires_at': fields.Datetime.now() + timedelta(seconds=expires_in - 60),
                        'last_refresh_date': fields.Datetime.now(),
                        'refresh_count': rec.refresh_count + 1,
                        'last_refresh_error': False,
                    })
                    _logger.info("Zalo Shared Token %s: refreshed (expires_in=%s)", rec.id, expires_in)
                    return result['access_token']
        except psycopg2.errors.LockNotAvailable:
            raise UserError(_("Token đang được refresh ở nơi khác hoặc form có thay đổi chưa lưu. "
                              "Lưu form rồi thử lại."))

        _logger.error("Zalo Shared Token %s: refresh failed: %s", self.id, error)
        raise UserError(_("Không refresh được Zalo token: %s") % error)

    def ensure_valid_token(self):
        """Refresh on-demand nếu token đã hết hạn.

        :return: access_token dùng được; nếu refresh lỗi thì trả token hiện có (có thể đã
                 hết hạn) để người gọi vẫn thử gửi như trước, lỗi đã được log và ghi lại
        """
        self.ensure_one()
        if not self._is_token_expired():
            return self.access_token
        _logger.warning("Zalo Shared Token %s: token expired, attempting on-demand refresh", self.id)
        try:
            return self._refresh_in_own_transaction()
        except UserError:
            return self.access_token

    def refresh_access_token(self):
        """Refresh bắt buộc, bỏ qua hạn token. Dùng cho cron, nút bấm, và khi Zalo báo
        access token không hợp lệ.

        :return: access_token mới của bản ghi cuối (thực tế chỉ có 1 bản ghi active)
        :raise UserError: khi refresh thất bại
        """
        access_token = False
        for rec in self:
            access_token = rec._refresh_in_own_transaction(force=True)
        return access_token

    @api.model
    def _get_shared_token(self):
        """
        Lấy access token của shared token manager đang active, tự refresh nếu hết hạn.

        :return: access_token (string) hoặc False nếu không có bản ghi active
        """
        token_manager = self.search([('active', '=', True)], limit=1)
        if not token_manager:
            _logger.error("No active Zalo Shared Token found")
            return False
        return token_manager.ensure_valid_token()

    def action_refresh_token(self):
        """Action button để manually refresh token"""
        self.ensure_one()
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
