from odoo import api, fields, models

from ..models.totp_admin_utils import build_otpauth_url, current_code, format_secret, qr_png_b64


class TotpSecretView(models.TransientModel):
    _name = 'hlv.totp.secret.view'
    _description = "Màn hình admin xem khoá 2FA"

    user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='cascade')
    # Các field dưới tính từ user mỗi lần mở, không lưu: khoá không nằm lại bảng wizard chờ dọn.
    secret = fields.Char(string="Khoá", compute='_compute_secret')
    url = fields.Char(compute='_compute_secret')
    qrcode = fields.Binary(string="QR", compute='_compute_secret')
    code = fields.Char(string="Mã 6 số hiện tại", compute='_compute_secret')

    @api.depends('user_id')
    def _compute_secret(self):
        for wizard in self:
            user = wizard.user_id.sudo()
            raw = user.totp_secret
            wizard.secret = format_secret(raw)
            wizard.url = build_otpauth_url(raw, user.login, user.company_id.display_name)
            wizard.qrcode = qr_png_b64(wizard.url)
            wizard.code = current_code(raw)

    def action_refresh_code(self):
        """Mở lại chính màn hình này để đọc lại mã (mã đổi mỗi 30 giây)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.user_id.name,
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
