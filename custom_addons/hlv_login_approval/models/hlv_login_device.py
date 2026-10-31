import logging
import secrets

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.http import GeoIP
from odoo.addons.base.models.res_users import check_identity

from .login_approval_utils import (
    approval_expiry, is_approval_valid, is_request_open, join_match_choices, parse_positive_int,
    request_expiry, split_match_choices)

_logger = logging.getLogger(__name__)

DEFAULT_VALID_DAYS = 30
DEFAULT_REQUEST_MINUTES = 30
# Số khớp 2 chữ số như Google; người duyệt chọn 1 trong MATCH_CHOICES số.
MATCH_CODE_MIN, MATCH_CODE_MAX = 10, 99
MATCH_CHOICES = 3
BUS_NOTIFICATION = 'hlv_login_approval/update'


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
        ('expired', 'Hết hạn'),
        ('cancelled', 'Đã huỷ'),
    ], string='Trạng thái', default='pending', required=True, readonly=True)
    # Cùng tên và cách lấy với res.device.log để admin so được với danh sách phiên của user.
    ip_address = fields.Char(string='IP', readonly=True)
    platform = fields.Char(string='Hệ điều hành', readonly=True)
    browser = fields.Char(string='Trình duyệt', readonly=True)
    country = fields.Char(string='Quốc gia', readonly=True)
    city = fields.Char(string='Thành phố', readonly=True)
    request_date = fields.Datetime(string='Yêu cầu lúc', default=fields.Datetime.now, readonly=True)
    # Yêu cầu chỉ chờ trong thời gian ngắn: duyệt một yêu cầu cũ là mở cửa cho trình duyệt
    # có thể đã không còn trong tay người dùng.
    request_until = fields.Datetime(string='Yêu cầu hết hạn lúc', readonly=True)
    approved_by_id = fields.Many2one('res.users', string='Người duyệt', readonly=True)
    approved_date = fields.Datetime(string='Duyệt lúc', readonly=True)
    approved_until = fields.Datetime(string='Hiệu lực đến', readonly=True)
    last_login_date = fields.Datetime(string='Đăng nhập gần nhất', readonly=True)
    # Số hiện trên trang chờ; người duyệt phải hỏi người đang ngồi trước máy mới biết để chọn.
    # Không đưa vào view hay email, và chỉ admin đọc được qua ORM (xuất dữ liệu...).
    match_code = fields.Char(readonly=True, copy=False, groups='base.group_system')
    # Bộ số cho người duyệt chọn, chốt một lần cùng match_code. Nếu mỗi lần mở hộp chọn lại
    # sinh số mồi mới thì mở vài lần là thấy số nào lặp lại, tức là số đúng.
    match_choices = fields.Char(readonly=True, copy=False, groups='base.group_system')
    session_ids = fields.One2many(related='user_id.device_ids', string='Phiên đang mở của user')
    # Trang chờ (chưa đăng nhập) nghe kênh bus dạng chuỗi; bus cho khách subscribe kênh
    # chuỗi bất kỳ nên tên kênh phải ngẫu nhiên, không đoán được từ id.
    bus_channel = fields.Char(readonly=True, copy=False)

    _sql_constraints = [
        ('user_token_uniq', 'unique(user_id, token_hash)',
         'Thiết bị này đã được ghi nhận cho người dùng.'),
    ]

    @api.depends('user_id.name', 'ip_address')
    def _compute_display_name(self):
        for device in self:
            device.display_name = f"{device.user_id.name} – {device.ip_address or '?'}"

    def action_approve(self):
        """Mở hộp chọn số khớp; duyệt thật nằm ở _approve_with_code."""
        self.ensure_one()
        self._check_can_approve()
        wizard = self.env['hlv.login.device.approve'].create({
            'device_id': self.id,
            **{f'choice_{i}': code
               for i, code in enumerate(split_match_choices(self.sudo().match_choices), start=1)},
        })
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Chọn số trên màn hình của %s", self.user_id.name),
            'res_model': wizard._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _approve_with_code(self, code):
        """Duyệt nếu chọn đúng số; chọn sai thì huỷ yêu cầu. Trả True khi đã duyệt.

        Huỷ chứ không cho chọn lại: chọn lại được thì bấm lần lượt 3 số kiểu gì cũng trúng.
        """
        self.ensure_one()
        self._check_can_approve()
        if code and code == self.sudo().match_code:
            self.write(self._approval_vals(self.env.user))
            approved = True
        else:
            _logger.warning("hlv_login_approval: %s chọn sai số khi duyệt thiết bị %s, huỷ yêu cầu",
                            self.env.user.login, self.id)
            self.write({'state': 'cancelled'})
            approved = False
        self._notify_waiting_browser()
        return approved

    def _check_can_approve(self):
        self.ensure_one()
        if self.user_id == self.env.user:
            raise UserError(self.env._(
                "Không được tự duyệt thiết bị của chính mình, nhờ người duyệt khác."))
        if not self._is_request_open():
            raise UserError(self.env._(
                "Yêu cầu không còn chờ duyệt (đã hết hạn hoặc đã xử lý). "
                "Người dùng đăng nhập lại sẽ tạo yêu cầu mới với số mới."))

    def action_unblock(self):
        # Thiết bị bị từ chối không vào được trang chờ nên không có số để khớp; bỏ chặn chỉ cho
        # phép xin lại, lần đăng nhập sau tạo yêu cầu mới có số và vẫn phải duyệt.
        self.filtered(lambda d: d.state == 'rejected').write({'state': 'cancelled'})

    def action_reject(self):
        # Cookie thiết bị không gắn với phiên cụ thể nào trong res.device (sid đổi mỗi lần
        # đăng nhập), nên thu hồi thiết bị đã duyệt phải đóng mọi phiên của user. Các thiết bị
        # còn được duyệt chỉ cần nhập lại mật khẩu, không phải xin duyệt lại.
        users_to_logout = self.filtered(lambda d: d.state == 'approved').user_id
        self.write({'state': 'rejected', 'approved_until': False})
        # sudo: người duyệt không có quyền Settings chỉ đọc được res.device của chính mình.
        for user in users_to_logout:
            user.sudo()._action_revoke_all_devices()
        self._notify_waiting_browser()

    @check_identity
    def action_revoke_user_sessions(self):
        # Đóng mọi phiên mà không từ chối thiết bị: dùng khi nghi lộ phiên nhưng máy vẫn đúng chủ.
        # sudo như action_reject vì người duyệt có thể không phải admin.
        for user in self.user_id:
            user.sudo()._action_revoke_all_devices()

    def action_open_user_sessions(self):
        action = self.env['ir.actions.act_window']._for_xml_id('hlv_login_approval.action_hlv_login_sessions')
        action['domain'] = [('user_id', 'in', self.user_id.ids)]
        action['context'] = {}
        return action

    @api.model
    def _cron_expire_requests(self):
        stale = self.search([('state', '=', 'pending'), '|',
                             ('request_until', '=', False), ('request_until', '<=', fields.Datetime.now())])
        stale.write({'state': 'expired'})
        stale._notify_waiting_browser()

    @api.model
    def _approval_vals(self, approver):
        now = fields.Datetime.now()
        return {
            'state': 'approved',
            'approved_by_id': approver.id,
            'approved_date': now,
            'approved_until': approval_expiry(now, self._valid_days()),
        }

    @api.model
    def _valid_days(self):
        value = self.env['ir.config_parameter'].sudo().get_param('hlv_login_approval.valid_days')
        return parse_positive_int(value, DEFAULT_VALID_DAYS)

    @api.model
    def _request_minutes(self):
        value = self.env['ir.config_parameter'].sudo().get_param('hlv_login_approval.request_minutes')
        return parse_positive_int(value, DEFAULT_REQUEST_MINUTES)

    def _is_valid_now(self):
        self.ensure_one()
        return is_approval_valid(self.state, self.approved_until, fields.Datetime.now())

    def _is_request_open(self):
        self.ensure_one()
        # Yêu cầu tạo trước khi có số khớp thì không duyệt được nữa: coi như hết hạn để
        # lần đăng nhập sau tạo yêu cầu mới có số.
        return bool(self.sudo().match_code) and is_request_open(
            self.state, self.request_until, fields.Datetime.now())

    def _waiting_state(self):
        """Trạng thái hiển thị cho trang chờ: tính hạn ngay, không đợi cron đổi state."""
        self.ensure_one()
        if self._is_valid_now():
            return 'approved'
        if self.state in ('pending', 'expired') and not self._is_request_open():
            return 'expired'
        return self.state

    @api.model
    def _new_match_vals(self):
        """Số khớp mới cùng bộ số cho người duyệt chọn (gồm số đúng và số mồi)."""
        numbers = secrets.SystemRandom().sample(range(MATCH_CODE_MIN, MATCH_CODE_MAX + 1), MATCH_CHOICES)
        return {
            'match_code': str(numbers[0]),
            'match_choices': join_match_choices(numbers),
        }

    @api.model
    def _register_attempt(self, user_id, token_hash, ip_address, platform, browser, auto_approve=False):
        """Ghi nhận lần đăng nhập từ thiết bị chưa hợp lệ, trả bản ghi thiết bị.

        Thiết bị hết hạn duyệt hoặc yêu cầu cũ hết hạn chờ thì mở yêu cầu mới và báo người duyệt lại.
        auto_approve (tài khoản cứu hộ): duyệt luôn, email chỉ để người duyệt biết.
        """
        device = self.search([('user_id', '=', user_id), ('token_hash', '=', token_hash)], limit=1)
        if device and not auto_approve and (device.state == 'rejected' or device._is_request_open()):
            # Không gửi lại email mỗi lần user bấm đăng nhập, tránh dội hộp thư admin.
            return device
        geoip = GeoIP(ip_address)
        now = fields.Datetime.now()
        vals = {
            'state': 'pending',
            'ip_address': ip_address,
            'platform': platform,
            'browser': browser,
            'country': geoip.get('country_name'),
            'city': geoip.get('city'),
            'request_date': now,
            'request_until': request_expiry(now, self._request_minutes()),
            'approved_until': False,
            'bus_channel': f"hlv_login_approval_{secrets.token_urlsafe(24)}",
            **({'match_code': False, 'match_choices': False} if auto_approve else self._new_match_vals()),
        }
        if auto_approve:
            vals.update(self._approval_vals(self.env['res.users'].browse(user_id)))
        if device:
            device.write(vals)
        else:
            device = self.create(dict(vals, user_id=user_id, token_hash=token_hash))
        device._notify_approvers()
        return device

    def _notify_waiting_browser(self):
        for device in self.filtered('bus_channel'):
            self.env['bus.bus']._sendone(device.bus_channel, BUS_NOTIFICATION, {'state': device.state})

    def _notify_approvers(self):
        self.ensure_one()
        approvers = self.env['res.users'].search([
            ('groups_id', 'in', self.env.ref('hlv_login_approval.group_login_approver').id),
            ('id', '!=', self.user_id.id),
            ('email', '!=', False),
        ])
        if not approvers:
            _logger.warning("hlv_login_approval: không có người duyệt nào có email để báo thiết bị %s", self.id)
            return
        template = self.env.ref('hlv_login_approval.mail_template_login_request').with_context(
            hlv_match_choices=split_match_choices(self.sudo().match_choices))
        template.send_mail(self.id, email_values={'email_to': ','.join(approvers.mapped('email_formatted'))})
