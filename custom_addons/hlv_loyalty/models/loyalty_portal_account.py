# -*- coding: utf-8 -*-
import hashlib
import os
import re
from odoo import models, fields, api, exceptions


class HlvLoyaltyPortalAccount(models.Model):
    _name = 'hlv.loyalty.portal.account'
    _description = 'Tài khoản cổng Loyalty'
    _order = 'partner_id asc'

    partner_id = fields.Many2one(
        'res.partner', string='Khách hàng', required=True,
        ondelete='cascade', index=True,
    )
    username = fields.Char(
        string='Tên đăng nhập', required=True, copy=False, index=True,
    )
    password_hash = fields.Char(string='Mật khẩu (hash)', copy=False)
    active = fields.Boolean(default=True)

    # Convenience: mirror phone from partner so users can update it here
    phone = fields.Char(
        string='Số điện thoại', related='partner_id.phone',
        readonly=False, store=False,
    )

    _sql_constraints = [
        ('username_uniq', 'UNIQUE(username)', 'Tên đăng nhập đã tồn tại.'),
    ]

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
        Accepts username OR phone number as login.
        """
        login = (login or '').strip()
        plain_password = (plain_password or '').strip()
        if not login or not plain_password:
            return False

        # Normalize phone: strip spaces/dashes for comparison
        phone_normalized = re.sub(r'[\s\-\.]', '', login)

        domain = [
            ('active', '=', True),
            '|',
            ('username', '=', login),
            ('partner_id.phone', '=', phone_normalized),
        ]
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
