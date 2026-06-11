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
    password_hash = fields.Char(string='Mật khẩu (hash)', copy=False)
    active = fields.Boolean(default=True)

    # Dedicated login phone – stored separately, defaults to partner's phone
    portal_phone = fields.Char(
        string='SĐT đăng nhập',
        help='Số điện thoại dùng để đăng nhập cổng Loyalty. '
             'Mặc định lấy từ SĐT của khách hàng. Lưu dưới dạng chuẩn hóa (0xxxxxxxxx).',
        index=True,
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
        return super().create(vals_list)

    def write(self, vals):
        if 'portal_phone' in vals:
            vals['portal_phone'] = _normalize_phone(vals['portal_phone'] or '')
        return super().write(vals)

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

    def name_get(self):
        result = []
        for acc in self:
            name = f'{acc.partner_id.name} ({acc.username})'
            result.append((acc.id, name))
        return result

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
