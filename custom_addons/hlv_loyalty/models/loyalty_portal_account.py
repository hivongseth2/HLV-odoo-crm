# -*- coding: utf-8 -*-
import hashlib
import os
import re
from odoo import models, fields, api, exceptions


def _normalize_phone(phone: str) -> str:
    """Strip non-digits; convert +84/84 prefix → 0 (Vietnamese standard)."""
    if not phone:
        return ''
    digits = re.sub(r'\D', '', phone)
    # +84xxxxxxxxx (11 digits starting with 84) → 0xxxxxxxxx
    if len(digits) == 11 and digits.startswith('84'):
        digits = '0' + digits[2:]
    # 084xxxxxxxxx (12 digits starting with 084) is unlikely but handle it
    elif len(digits) == 12 and digits.startswith('084'):
        digits = '0' + digits[3:]
    return digits


class HlvLoyaltyPortalAccount(models.Model):
    _name = 'hlv.loyalty.portal.account'
    _description = 'Tài khoản cổng Loyalty'
    _order = 'partner_id asc'

    partner_id = fields.Many2one(
        'res.partner', string='Khách hàng', required=True,
        ondelete='cascade', index=True,
        domain=[('is_company', '=', True), ('parent_id', '=', False), ('active', '=', True)],
    )
    username = fields.Char(
        string='Tên đăng nhập', required=True, copy=False, index=True,
    )
    display_name = fields.Char(
        string='Tên hiển thị', compute='_compute_display_name', store=True,
        help='Lưu cứng (store=True) để mọi nơi (list, search, name_search, '
             'string dùng trong mô tả/công thức điểm) luôn ra đúng tên, '
             'không phụ thuộc việc client có gọi đúng compute hay không.',
    )
    password_hash = fields.Char(string='Mật khẩu (hash)', copy=False)
    active = fields.Boolean(default=True)

    # Dedicated login phone – stored separately, defaults to partner's phone
    portal_phone = fields.Char(
        string='SĐT đăng nhập',
        help='Số điện thoại dùng để đăng nhập cổng Loyalty. '
             'Mặc định lấy từ SĐT của khách hàng. Lưu dưới dạng chuẩn hóa (0xxxxxxxxx).',
        index=True,
    )

    # ── Multi-account per company ────────────────────────────────────────────
    buyer_name = fields.Char(
        string='Tên thu mua',
        help='Tên người/bộ phận thu mua gắn với tài khoản này (VD: "Anh A - phòng thu mua 1").',
    )
    default_earning_pct = fields.Float(
        string='% cộng điểm mặc định',
        digits=(5, 2),
        help='% chiết khấu mặc định dùng để tính điểm đổi thưởng khi tài khoản này '
             'được chọn trên đơn bán hàng. VD: 5 = 5%. Sales có thể sửa lại trên từng đơn.',
    )
    is_default = fields.Boolean(
        string='Tài khoản mặc định',
        help='Tài khoản được tự động dùng để cộng điểm khi đơn bán hàng không chọn '
             'tài khoản nào. Mỗi công ty chỉ có tối đa 1 tài khoản mặc định.',
    )

    # ── Điểm (mỗi tài khoản có pool điểm riêng — nguồn sự thật là hlv.loyalty.history) ──
    loyalty_history_ids = fields.One2many(
        'hlv.loyalty.history', 'account_id', string='Lịch sử điểm',
    )
    loyalty_total_points = fields.Integer(
        string='Điểm xếp hạng', compute='_compute_loyalty_total_points',
        store=True, readonly=True,
        help='Điểm xếp hạng tự động xác nhận, riêng của tài khoản này.',
    )
    loyalty_exchange_points = fields.Integer(
        string='Điểm đổi thưởng', compute='_compute_loyalty_exchange_points',
        store=True, readonly=True,
        help='Điểm đổi thưởng đã xác nhận, riêng của tài khoản này.',
    )
    loyalty_pending_points = fields.Integer(
        string='Điểm chờ xác nhận', compute='_compute_loyalty_pending_points',
        store=False, readonly=True,
    )
    loyalty_reward_pending_points = fields.Integer(
        string='Điểm đổi thưởng đang treo',
        compute='_compute_loyalty_reward_request_points',
        store=False, readonly=True,
        help='Tổng điểm của các yêu cầu đổi thưởng đang chờ xử lý của tài khoản này.',
    )
    loyalty_exchange_available_points = fields.Integer(
        string='Điểm đổi thưởng khả dụng',
        compute='_compute_loyalty_reward_request_points',
        store=False, readonly=True,
        help='Điểm đổi thưởng còn có thể dùng sau khi trừ điểm đang treo.',
    )

    _sql_constraints = [
        ('username_uniq', 'UNIQUE(username)', 'Tên đăng nhập đã tồn tại.'),
    ]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @api.onchange('partner_id')
    def _onchange_partner_id_phone(self):
        """Pre-fill portal_phone from partner when partner is selected."""
        if self.partner_id and not self.portal_phone:
            self.portal_phone = _normalize_phone(self.partner_id.phone or '')

    @api.model_create_multi
    def create(self, vals_list):
        company = self.env.company
        default_pw = getattr(company, 'loyalty_portal_default_password', None) or 'hlv@2026'
        for vals in vals_list:
            # Auto-fill portal_phone from partner if not provided
            if not vals.get('portal_phone') and vals.get('partner_id'):
                partner = self.env['res.partner'].browse(vals['partner_id'])
                vals['portal_phone'] = _normalize_phone(partner.phone or '')
            else:
                vals['portal_phone'] = _normalize_phone(vals.get('portal_phone') or '')
            # Set default password hash if no hash provided
            if not vals.get('password_hash'):
                vals['password_hash'] = self._hash_password(default_pw)
        records = super().create(vals_list)
        records.filtered('is_default')._unset_sibling_defaults()
        return records

    def write(self, vals):
        if 'portal_phone' in vals:
            vals['portal_phone'] = _normalize_phone(vals['portal_phone'] or '')
        result = super().write(vals)
        if vals.get('is_default'):
            self._unset_sibling_defaults()
        return result

    def _unset_sibling_defaults(self):
        """Đảm bảo mỗi công ty (partner_id) chỉ có tối đa 1 tài khoản mặc định."""
        for account in self:
            siblings = self.search([
                ('partner_id', '=', account.partner_id.id),
                ('is_default', '=', True),
                ('id', '!=', account.id),
            ])
            if siblings:
                siblings.write({'is_default': False})

    # ── Password helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _hash_password(plain: str) -> str:
        salt = os.urandom(16).hex()
        h = hashlib.sha256((salt + plain).encode()).hexdigest()
        return f'{salt}${h}'

    @staticmethod
    def _verify_password(plain: str, stored: str) -> bool:
        if not stored or '$' not in stored:
            return False
        salt, h = stored.split('$', 1)
        return hashlib.sha256((salt + plain).encode()).hexdigest() == h

    def set_password(self, plain: str):
        """Hash and store a new password (validated for length ≥ 6)."""
        if not plain or len(plain) < 6:
            raise exceptions.UserError('Mật khẩu phải có ít nhất 6 ký tự.')
        self.password_hash = self._hash_password(plain)

    def reset_password(self, new_plain: str):
        """Admin reset — no old-password check needed."""
        self.set_password(new_plain)

    # ── Điểm (nguồn sự thật: hlv.loyalty.history.account_id) ────────────────────

    @api.depends(
        'loyalty_history_ids', 'loyalty_history_ids.point_amount',
        'loyalty_history_ids.point_type', 'loyalty_history_ids.state',
    )
    def _compute_loyalty_total_points(self):
        """Điểm xếp hạng: ranking confirmed (+ legacy point_type=False)."""
        for account in self:
            records = account.loyalty_history_ids.filtered(
                lambda h: h.point_type in ('ranking', False) and h.state in ('confirmed', False)
            )
            account.loyalty_total_points = sum(records.mapped('point_amount'))

    @api.depends(
        'loyalty_history_ids', 'loyalty_history_ids.point_amount',
        'loyalty_history_ids.point_type', 'loyalty_history_ids.state',
    )
    def _compute_loyalty_exchange_points(self):
        """Điểm đổi thưởng: exchange confirmed (+ legacy point_type=False)."""
        for account in self:
            records = account.loyalty_history_ids.filtered(
                lambda h: h.point_type in ('exchange', False) and h.state in ('confirmed', False)
            )
            account.loyalty_exchange_points = sum(records.mapped('point_amount'))

    @api.depends(
        'loyalty_history_ids', 'loyalty_history_ids.point_amount',
        'loyalty_history_ids.point_type', 'loyalty_history_ids.state',
    )
    def _compute_loyalty_pending_points(self):
        """Điểm exchange đang chờ xác nhận."""
        for account in self:
            records = account.loyalty_history_ids.filtered(
                lambda h: h.point_type == 'exchange' and h.state == 'pending'
            )
            account.loyalty_pending_points = sum(records.mapped('point_amount'))

    def _get_loyalty_pending_reward_requests(self, exclude_request=None):
        self.ensure_one()
        domain = [('account_id', '=', self.id), ('state', '=', 'pending')]
        exclude_ids = []
        if exclude_request:
            exclude_ids = exclude_request.ids if hasattr(exclude_request, 'ids') else [int(exclude_request)]
        if exclude_ids:
            domain.append(('id', 'not in', exclude_ids))
        return self.env['hlv.loyalty.reward.request'].sudo().search(domain)

    def _get_loyalty_pending_reward_points(self, exclude_request=None):
        self.ensure_one()
        requests = self._get_loyalty_pending_reward_requests(exclude_request=exclude_request)
        return sum(requests.mapped('points_required'))

    @api.depends('loyalty_exchange_points')
    def _compute_loyalty_reward_request_points(self):
        for account in self:
            pending_points = account._get_loyalty_pending_reward_points()
            account.loyalty_reward_pending_points = pending_points
            account.loyalty_exchange_available_points = max(
                (account.loyalty_exchange_points or 0) - pending_points, 0
            )

    # ── Authentication ────────────────────────────────────────────────────────

    @api.model
    def authenticate(self, login: str, plain_password: str):
        """
        Return the account record if credentials are valid, else False.
        Accepts username OR portal_phone as login.
        Phone input is normalized before comparison.
        """
        login = (login or '').strip()
        plain_password = (plain_password or '').strip()
        if not login or not plain_password:
            return False

        # Normalize login as phone and search both username and portal_phone
        phone_normalized = _normalize_phone(login)

        domain = [('active', '=', True)]
        if phone_normalized:
            domain += ['|', ('username', '=', login), ('portal_phone', '=', phone_normalized)]
        else:
            domain += [('username', '=', login)]

        accounts = self.sudo().search(domain)
        for acc in accounts:
            if self._verify_password(plain_password, acc.password_hash):
                return acc
        return False

    # ── Display ───────────────────────────────────────────────────────────────

    @api.depends('partner_id.name', 'buyer_name', 'username')
    def _compute_display_name(self):
        """Tên hiển thị dùng ở mọi Many2one/dropdown (VD wizard chuyển điểm).

        Ghi đè bằng field compute+store chuẩn Odoo 17+ thay vì name_get()
        kiểu cũ — name_get() đôi khi không được web client mới resolve
        đúng, khiến ô chọn hiện text thô dạng "hlv.loyalty.portal.account,69"
        thay vì tên. Định dạng: "Công ty - Tên thu mua (username)", hoặc
        "Công ty (username)" nếu chưa nhập tên thu mua.
        """
        for acc in self:
            label = acc.partner_id.name or ''
            if acc.buyer_name:
                label = f'{label} - {acc.buyer_name}' if label else acc.buyer_name
            acc.display_name = f'{label} ({acc.username})' if acc.username else label

    def action_reset_password_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reset mật khẩu',
            'res_model': 'hlv.loyalty.reset.password.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_account_id': self.id},
        }

    def action_recalculate_points_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Tính lại điểm Loyalty',
            'res_model': 'hlv.loyalty.recalculate.points.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_account_id': self.id},
        }

    def action_open_point_transfer_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Chuyển điểm Loyalty',
            'res_model': 'hlv.loyalty.point.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_source_account_id': self.id},
        }
