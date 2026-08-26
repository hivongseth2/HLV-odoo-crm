# -*- coding: utf-8 -*-
import re
from odoo import models, fields, api
from odoo.exceptions import UserError


def _normalize_phone(phone: str) -> str:
    if not phone:
        return ''
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 11 and digits.startswith('84'):
        digits = '0' + digits[2:]
    elif len(digits) == 12 and digits.startswith('084'):
        digits = '0' + digits[3:]
    return digits


class HlvLoyaltyPortalAccount(models.Model):
    _inherit = 'hlv.loyalty.portal.account'

    @api.model
    def pos_lookup_or_create_account(self, phone, partner_id=False):
        """
        Tra cứu tài khoản Portal theo SĐT.
        Nếu chưa tồn tại: tự động tạo mới nhanh tài khoản Portal (Phương án A).
        """
        normalized_phone = _normalize_phone(phone)
        if not normalized_phone or len(normalized_phone) < 9:
            raise UserError('Số điện thoại không hợp lệ.')

        account = self.sudo().search([('portal_phone', '=', normalized_phone)], limit=1)
        if not account:
            if not partner_id:
                partner_id = self.env.ref('base.partner_admin').id

            default_pw = getattr(self.env.company, 'loyalty_portal_default_password', None) or 'hlv@2026'
            account = self.sudo().create({
                'partner_id': partner_id,
                'username': normalized_phone,
                'portal_phone': normalized_phone,
                'buyer_name': f'Khách hàng {normalized_phone}',
                'password_hash': self._hash_password(default_pw),
            })

        tier = account.partner_id.loyalty_tier_id if account.partner_id else False
        return {
            'id': account.id,
            'name': account.display_name or account.buyer_name or account.portal_phone,
            'phone': account.portal_phone,
            'ranking_points': account.loyalty_total_points,
            'exchange_points': account.loyalty_exchange_available_points,
            'tier_name': tier.name if tier else 'Thành viên',
            'tier_color': tier.badge_color if tier else '#1779b4',
        }
