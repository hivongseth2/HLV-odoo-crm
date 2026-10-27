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


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _check_credentials(self, credential, env):
        # Kiểm mật khẩu trước: sai mật khẩu thì không được tạo yêu cầu duyệt hay làm phiền admin.
        auth_info = super()._check_credentials(credential, env)
        if self._login_needs_device_approval(env):
            self._enforce_device_approval()
        return auth_info

    def _login_needs_device_approval(self, env):
        user = self.env.user
        # XML-RPC / API key (interactive=False) và cron không có trình duyệt để duyệt;
        # các tích hợp sheet giá, Zalo... đi đường này nên phải để nguyên.
        if not request or not env.get('interactive', True):
            return False
        # Đã đăng nhập sẵn trên trình duyệt này: đây là đổi mật khẩu / xác minh danh tính.
        if request.session.uid == user.id:
            return False
        # Admin được miễn để không ai tự khoá mình ra khỏi chỗ duyệt.
        return user._is_internal() and not user.has_group('base.group_system')

    def _enforce_device_approval(self):
        user = self.env.user
        token = request.httprequest.cookies.get(DEVICE_COOKIE)
        if not token:
            token = secrets.token_urlsafe(32)
            request.future_response.set_cookie(
                DEVICE_COOKIE, token, max_age=DEVICE_COOKIE_MAX_AGE, httponly=True,
                secure=request.httprequest.scheme == 'https', samesite='Lax')
        token_hash = hash_device_token(token)

        device = self.env['hlv.login.device'].sudo().search(
            [('user_id', '=', user.id), ('token_hash', '=', token_hash)], limit=1)
        if device and device._is_valid_now():
            device.last_login_date = fields.Datetime.now()
            return

        # AccessDenied bên dưới làm cursor đăng nhập rollback, nên yêu cầu duyệt phải ghi
        # bằng cursor riêng (tự commit khi thoát with) thì admin mới thấy.
        with self.env.registry.cursor() as cr:
            # Lấy platform/browser đúng như Session.update_trace để khớp với res.device.
            user_agent = request.httprequest.user_agent
            state = self.env(cr=cr, su=True)['hlv.login.device']._register_attempt(
                user.id, token_hash, request.httprequest.remote_addr,
                user_agent.platform, user_agent.browser,
            )
        # Core chỉ log "Login failed" giống hệt sai mật khẩu; dòng này để phân biệt.
        _logger.info("hlv_login_approval: chặn %s từ thiết bị chưa duyệt (state=%s)", user.login, state)
        if state == 'rejected':
            raise AccessDenied(self.env._(
                "Quản trị viên đã từ chối đăng nhập từ thiết bị này. Liên hệ quản trị viên nếu cần."))
        raise AccessDenied(self.env._(
            "Thiết bị này chưa được duyệt đăng nhập. Yêu cầu đã gửi tới quản trị viên, "
            "vui lòng đăng nhập lại sau khi được duyệt."))
