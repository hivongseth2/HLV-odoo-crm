# -*- coding: utf-8 -*-
import re
from odoo import http
from odoo.http import request
from odoo.exceptions import UserError

_SESSION_KEY = 'hlv_loyalty_account_id'


def _get_current_account():
    """Return the logged-in portal account or None."""
    account_id = request.session.get(_SESSION_KEY)
    if not account_id:
        return None
    account = request.env['hlv.loyalty.portal.account'].sudo().browse(account_id)
    if not account.exists() or not account.active:
        request.session.pop(_SESSION_KEY, None)
        return None
    return account


def _load_partner_data(partner):
    """Load all dashboard data for a partner."""
    root = partner.commercial_partner_id or partner
    # Collect root + all direct children to catch points on child contacts/sub-companies
    all_partner_ids = [root.id] + root.child_ids.ids
    tiers = request.env['hlv.loyalty.tier'].sudo().search(
        [('active', '=', True)], order='min_points asc'
    )
    active_vouchers = request.env['hlv.loyalty.voucher'].sudo().search([
        ('partner_id', 'in', all_partner_ids),
        ('state', '=', 'active'),
    ])
    recent_history = request.env['hlv.loyalty.history'].sudo().search([
        ('partner_id', 'in', all_partner_ids),
    ], order='date desc', limit=10)
    next_tier = None
    if root.loyalty_tier_id:
        next_tier = request.env['hlv.loyalty.tier'].sudo().search([
            ('min_points', '>', root.loyalty_total_points),
            ('active', '=', True),
        ], order='min_points asc', limit=1)
    return {
        'tiers': tiers,
        'partner': root,
        'active_vouchers': active_vouchers,
        'recent_history': recent_history,
        'next_tier': next_tier,
        'masked_phone': _mask_phone(root.phone),
        'masked_email': _mask_email(root.email),
    }


class LoyaltyPublicPortal(http.Controller):

    # ── Home: login or dashboard ───────────────────────────────────────────

    @http.route('/loyalty', type='http', auth='public', website=True, sitemap=False)
    def loyalty_home(self, **kwargs):
        account = _get_current_account()
        if account:
            return request.redirect('/loyalty/dashboard')
        return request.render('hlv_loyalty.loyalty_public_login', {
            'error': None,
        })

    # ── Login ──────────────────────────────────────────────────────────────

    @http.route('/loyalty/login', type='http', auth='public', website=True,
                sitemap=False, methods=['POST'])
    def loyalty_login(self, **post):
        login = (post.get('login') or '').strip()
        password = (post.get('password') or '').strip()

        if not login or not password:
            return request.render('hlv_loyalty.loyalty_public_login', {
                'error': 'Vui lòng nhập tên đăng nhập và mật khẩu.',
            })

        account = request.env['hlv.loyalty.portal.account'].sudo().authenticate(
            login, password
        )
        if not account:
            return request.render('hlv_loyalty.loyalty_public_login', {
                'error': 'Tên đăng nhập hoặc mật khẩu không đúng.',
                'login_val': login,
            })

        request.session[_SESSION_KEY] = account.id
        return request.redirect('/loyalty/dashboard')

    # ── Logout ─────────────────────────────────────────────────────────────

    @http.route('/loyalty/logout', type='http', auth='public', website=True,
                sitemap=False, methods=['GET', 'POST'])
    def loyalty_logout(self, **kwargs):
        request.session.pop(_SESSION_KEY, None)
        return request.redirect('/loyalty')

    # ── Dashboard ─────────────────────────────────────────────────────────

    @http.route('/loyalty/dashboard', type='http', auth='public', website=True,
                sitemap=False)
    def loyalty_dashboard(self, **kwargs):
        account = _get_current_account()
        if not account:
            return request.redirect('/loyalty')
        data = _load_partner_data(account.partner_id)
        data['account'] = account
        data['success'] = kwargs.get('success')
        data['error'] = kwargs.get('error')
        return request.render('hlv_loyalty.loyalty_public_dashboard', data)

    # ── Change phone ──────────────────────────────────────────────────────

    @http.route('/loyalty/change-phone', type='http', auth='public', website=True,
                sitemap=False, methods=['POST'])
    def loyalty_change_phone(self, **post):
        account = _get_current_account()
        if not account:
            return request.redirect('/loyalty')

        new_phone = (post.get('new_phone') or '').strip()
        if not new_phone:
            data = _load_partner_data(account.partner_id)
            data['account'] = account
            data['phone_error'] = 'Số điện thoại không được để trống.'
            data['show_phone_modal'] = True
            return request.render('hlv_loyalty.loyalty_public_dashboard', data)

        if not re.match(r'^[\d\s\-\+]{7,15}$', new_phone):
            data = _load_partner_data(account.partner_id)
            data['account'] = account
            data['phone_error'] = 'Số điện thoại không hợp lệ.'
            data['show_phone_modal'] = True
            return request.render('hlv_loyalty.loyalty_public_dashboard', data)

        account.partner_id.sudo().write({'phone': new_phone})
        return request.redirect('/loyalty/dashboard?success=phone_updated')

    # ── Change password ───────────────────────────────────────────────────

    @http.route('/loyalty/change-password', type='http', auth='public', website=True,
                sitemap=False, methods=['POST'])
    def loyalty_change_password(self, **post):
        account = _get_current_account()
        if not account:
            return request.redirect('/loyalty')

        old_password = (post.get('old_password') or '').strip()
        new_password = (post.get('new_password') or '').strip()
        confirm_password = (post.get('confirm_password') or '').strip()

        error = None
        if not old_password or not new_password or not confirm_password:
            error = 'Vui lòng điền đầy đủ thông tin.'
        elif not account._verify_password(old_password, account.password_hash):
            error = 'Mật khẩu hiện tại không đúng.'
        elif new_password != confirm_password:
            error = 'Mật khẩu mới và xác nhận không khớp.'
        elif len(new_password) < 6:
            error = 'Mật khẩu mới phải có ít nhất 6 ký tự.'

        if error:
            data = _load_partner_data(account.partner_id)
            data['account'] = account
            data['pw_error'] = error
            data['show_pw_modal'] = True
            return request.render('hlv_loyalty.loyalty_public_dashboard', data)

        try:
            account.sudo().set_password(new_password)
        except UserError as e:
            data = _load_partner_data(account.partner_id)
            data['account'] = account
            data['pw_error'] = str(e)
            data['show_pw_modal'] = True
            return request.render('hlv_loyalty.loyalty_public_dashboard', data)

        return request.redirect('/loyalty/dashboard?success=password_changed')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mask_phone(phone):
    if not phone:
        return ''
    digits = ''.join(c for c in phone if c.isdigit())
    if len(digits) < 6:
        return '***'
    return digits[:3] + '*' * (len(digits) - 5) + digits[-2:]


def _mask_email(email):
    if not email:
        return ''
    if '@' not in email:
        return '***'
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        return local + '***@' + domain
    return local[:2] + '*' * (len(local) - 2) + '@' + domain
