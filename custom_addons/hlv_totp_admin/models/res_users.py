import logging

from odoo import _, models
from odoo.addons.base.models.res_users import check_identity
from odoo.exceptions import AccessError, UserError

from .totp_admin_utils import generate_secret

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _check_totp_admin(self):
        # Chặn ở server chứ không chỉ ẩn nút: nhân viên vẫn gọi được method qua RPC.
        if not (self.env.su or self.env.user.has_group('hlv_totp_admin.group_totp_admin')):
            raise AccessError(_("Chỉ nhóm 'Admin bảo mật 2FA' mới được thay đổi xác thực hai yếu tố."))

    def action_totp_enable_wizard(self):
        self._check_totp_admin()
        return super().action_totp_enable_wizard()

    def action_totp_disable(self):
        self._check_totp_admin()
        return super().action_totp_disable()

    @check_identity
    def action_totp_admin_issue(self):
        """Admin tạo khoá 2FA cho user rồi mở màn hình QR + khoá."""
        self.ensure_one()
        self._check_totp_admin()
        if self == self.env.user:
            # Ghi khoá đổi session token của chính mình → admin bị đăng xuất giữa chừng.
            raise UserError(_("Tài khoản của chính bạn: dùng nút bật 2FA thường."))
        if self.totp_enabled:
            raise UserError(_("Tài khoản này đã bật 2FA. Tắt trước nếu muốn cấp khoá mới."))
        self.sudo().totp_secret = generate_secret()
        self._log_totp_admin_access(_("cấp"))
        return self._open_totp_secret_view()

    @check_identity
    def action_totp_admin_show(self):
        """Admin xem khoá + QR + mã hiện tại của user đã bật 2FA."""
        self.ensure_one()
        self._check_totp_admin()
        if not self.totp_enabled:
            raise UserError(_("Tài khoản này chưa bật 2FA."))
        self._log_totp_admin_access(_("xem"))
        return self._open_totp_secret_view()

    def _open_totp_secret_view(self):
        wizard = self.env['hlv.totp.secret.view'].create({'user_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'name': _("Khoá 2FA của %s", self.name),
            'res_model': 'hlv.totp.secret.view',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _log_totp_admin_access(self, verb):
        """Ghi dấu vết ai lấy khoá của ai — khoá này đăng nhập thay được người khác."""
        _logger.info("2FA admin %s: uid #%s on %s %r", verb, self.env.user.id, self, self.login)
        self.partner_id.sudo().message_post(
            body=_("%(admin)s đã %(verb)s khoá 2FA của tài khoản này.", admin=self.env.user.name, verb=verb),
            message_type='comment', subtype_xmlid='mail.mt_note')
