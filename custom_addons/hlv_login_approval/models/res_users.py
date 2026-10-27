import logging
import secrets

from odoo import fields, models
from odoo.exceptions import AccessDenied
from odoo.http import request

from .login_approval_utils import hash_device_token

_logger = logging.getLogger(__name__)

DEVICE_COOKIE = 'hlv_device'
# Cookie sống lâu; hạn duyệt do bản ghi hlv.login.device quyết định, không phải cookie.
DEVICE_COOKIE_MAX_AGE = 5 * 365 * 24 * 3600
SESSION_DEVICE_KEY = 'hlv_login_device_id'
WAIT_URL = '/web/login/approval'


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _check_credentials(self, credential, env):
        # Kiểm mật khẩu trước: sai mật khẩu thì không được tạo yêu cầu duyệt hay làm phiền người duyệt.
        auth_info = super()._check_credentials(credential, env)
        if not self._login_needs_device_approval(env):
            return auth_info
        if self.env.user._is_login_rescue_account():
            # Không chờ ai duyệt để hệ thống không bao giờ kẹt khi không còn người duyệt nào
            # vào được; máy mới vẫn được ghi lại và báo người duyệt.
            self._register_login_device(auto_approve=True)
            return auth_info

        device = self._register_login_device()
        if device._is_valid_now():
            device.last_login_date = fields.Datetime.now()
            return auth_info
        if device.state == 'rejected':
            raise AccessDenied(self.env._(
                "Người duyệt đã từ chối đăng nhập từ thiết bị này. Liên hệ quản trị viên nếu cần."))

        # Thiết bị chờ duyệt: để Odoo giữ phiên ở trạng thái chưa hoàn tất (như chờ mã 2FA)
        # rồi _mfa_url đưa sang trang chờ. 'enforce' để cả cách đăng nhập tự bỏ qua MFA
        # (passkey trả 'skip') cũng phải đi qua bước này.
        request.session[SESSION_DEVICE_KEY] = device.id
        _logger.info("hlv_login_approval: %s chờ duyệt thiết bị %s", self.env.user.login, device.id)
        return dict(auth_info, mfa='enforce')

    def _mfa_url(self):
        if self._login_device_pending():
            return WAIT_URL
        return super()._mfa_url()

    def _login_needs_device_approval(self, env):
        user = self.env.user
        # XML-RPC / API key (interactive=False) và cron không có trình duyệt để duyệt;
        # các tích hợp sheet giá, Zalo... đi đường này nên phải để nguyên.
        if not request or not env.get('interactive', True):
            return False
        # Đã đăng nhập sẵn trên trình duyệt này: đây là đổi mật khẩu / xác minh danh tính.
        if request.session.uid == user.id:
            return False
        return user._is_internal()

    def _is_login_rescue_account(self):
        # Chỉ miễn khi đã bật 2FA: miễn duyệt cho tài khoản chỉ có mật khẩu là để ngỏ cửa hậu.
        self.ensure_one()
        return self == self.env.ref('base.user_admin', raise_if_not_found=False) and self.totp_enabled

    def _register_login_device(self, auto_approve=False):
        """Tìm thiết bị theo cookie trình duyệt; chưa hợp lệ thì ghi nhận yêu cầu duyệt."""
        user = self.env.user
        token = request.httprequest.cookies.get(DEVICE_COOKIE)
        if not token:
            token = secrets.token_urlsafe(32)
            request.future_response.set_cookie(
                DEVICE_COOKIE, token, max_age=DEVICE_COOKIE_MAX_AGE, httponly=True,
                secure=request.httprequest.scheme == 'https', samesite='Lax')
        token_hash = hash_device_token(token)

        Device = self.env['hlv.login.device'].sudo()
        device = Device.search([('user_id', '=', user.id), ('token_hash', '=', token_hash)], limit=1)
        if device and device._is_valid_now():
            return device
        # Lấy platform/browser đúng như Session.update_trace để khớp với res.device.
        user_agent = request.httprequest.user_agent
        return Device._register_attempt(
            user.id, token_hash, request.httprequest.remote_addr,
            user_agent.platform, user_agent.browser, auto_approve=auto_approve)

    def _login_device_in_session(self):
        """Thiết bị gắn với phiên đăng nhập dở hiện tại, chỉ khi nó thuộc về user này."""
        self.ensure_one()
        Device = self.env['hlv.login.device'].sudo()
        device_id = request and request.session.get(SESSION_DEVICE_KEY)
        device = Device.browse(device_id).exists() if device_id else Device
        return device if device.user_id == self else Device

    def _login_device_pending(self):
        device = self._login_device_in_session()
        return bool(device) and not device._is_valid_now()
