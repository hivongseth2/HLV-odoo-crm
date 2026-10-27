import logging

from odoo import api, fields, models
from odoo.http import GeoIP

from .login_approval_utils import approval_expiry, is_approval_valid, parse_positive_int

_logger = logging.getLogger(__name__)

DEFAULT_VALID_DAYS = 30


class HlvLoginDevice(models.Model):
    _name = 'hlv.login.device'
    _description = 'Thiết bị đăng nhập cần duyệt'
    _order = 'request_date desc, id desc'

    user_id = fields.Many2one(
        'res.users', string='Người dùng', required=True, ondelete='cascade', index=True, readonly=True)
    # Chỉ lưu hash của cookie: lộ DB cũng không dựng lại được cookie của thiết bị đã duyệt.
    token_hash = fields.Char(required=True, index=True, readonly=True)
    state = fields.Selection([
        ('pending', 'Chờ duyệt'),
        ('approved', 'Đã duyệt'),
        ('rejected', 'Từ chối'),
    ], string='Trạng thái', default='pending', required=True, readonly=True)
    # Cùng tên và cách lấy với res.device.log để admin so được với danh sách phiên của user.
    ip_address = fields.Char(string='IP', readonly=True)
    platform = fields.Char(string='Hệ điều hành', readonly=True)
    browser = fields.Char(string='Trình duyệt', readonly=True)
    country = fields.Char(string='Quốc gia', readonly=True)
    city = fields.Char(string='Thành phố', readonly=True)
    request_date = fields.Datetime(string='Yêu cầu lúc', default=fields.Datetime.now, readonly=True)
    approved_by_id = fields.Many2one('res.users', string='Người duyệt', readonly=True)
    approved_date = fields.Datetime(string='Duyệt lúc', readonly=True)
    approved_until = fields.Datetime(string='Hiệu lực đến', readonly=True)
    last_login_date = fields.Datetime(string='Đăng nhập gần nhất', readonly=True)
    session_ids = fields.One2many(related='user_id.device_ids', string='Phiên đang mở của user')

    _sql_constraints = [
        ('user_token_uniq', 'unique(user_id, token_hash)',
         'Thiết bị này đã được ghi nhận cho người dùng.'),
    ]

    @api.depends('user_id.name', 'ip_address')
    def _compute_display_name(self):
        for device in self:
            device.display_name = f"{device.user_id.name} – {device.ip_address or '?'}"

    def action_approve(self):
        now = fields.Datetime.now()
        self.write({
            'state': 'approved',
            'approved_by_id': self.env.uid,
            'approved_date': now,
            'approved_until': approval_expiry(now, self._valid_days()),
        })

    def action_reject(self):
        # Cookie thiết bị không gắn với phiên cụ thể nào trong res.device (sid đổi mỗi lần
        # đăng nhập), nên thu hồi thiết bị đã duyệt phải đóng mọi phiên của user. Các thiết bị
        # còn được duyệt chỉ cần nhập lại mật khẩu, không phải xin duyệt lại.
        users_to_logout = self.filtered(lambda d: d.state == 'approved').user_id
        self.write({'state': 'rejected', 'approved_until': False})
        for user in users_to_logout:
            user._action_revoke_all_devices()

    @api.model
    def _valid_days(self):
        value = self.env['ir.config_parameter'].sudo().get_param('hlv_login_approval.valid_days')
        return parse_positive_int(value, DEFAULT_VALID_DAYS)

    def _is_valid_now(self):
        self.ensure_one()
        return is_approval_valid(self.state, self.approved_until, fields.Datetime.now())

    @api.model
    def _register_attempt(self, user_id, token_hash, ip_address, platform, browser):
        """Ghi nhận lần đăng nhập từ thiết bị chưa hợp lệ, trả state để báo người dùng.

        Thiết bị đã duyệt nhưng hết hạn quay về 'pending' và báo admin lại.
        """
        device = self.search([('user_id', '=', user_id), ('token_hash', '=', token_hash)], limit=1)
        if device.state in ('pending', 'rejected'):
            # Không gửi lại email mỗi lần user bấm đăng nhập, tránh dội hộp thư admin.
            return device.state
        geoip = GeoIP(ip_address)
        vals = {
            'state': 'pending',
            'ip_address': ip_address,
            'platform': platform,
            'browser': browser,
            'country': geoip.get('country_name'),
            'city': geoip.get('city'),
            'request_date': fields.Datetime.now(),
            'approved_until': False,
        }
        if device:
            device.write(vals)
        else:
            device = self.create(dict(vals, user_id=user_id, token_hash=token_hash))
        device._notify_approvers()
        return 'pending'

    def _notify_approvers(self):
        self.ensure_one()
        approvers = self.env['res.users'].search([
            ('groups_id', 'in', self.env.ref('base.group_system').id),
            ('share', '=', False),
            ('email', '!=', False),
        ])
        if not approvers:
            _logger.warning("hlv_login_approval: không có admin nào có email để báo thiết bị %s", self.id)
            return
        template = self.env.ref('hlv_login_approval.mail_template_device_request')
        template.send_mail(self.id, email_values={'email_to': ','.join(approvers.mapped('email_formatted'))})
