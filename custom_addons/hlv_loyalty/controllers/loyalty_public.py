# -*- coding: utf-8 -*-
import re
from datetime import timezone, timedelta as dt_timedelta
from odoo import http
from odoo.http import request
from odoo.exceptions import UserError

_VN_TZ = timezone(dt_timedelta(hours=7))


def _vn_datetime(dt, fmt):
    """Format a UTC Datetime to Vietnam local time (UTC+7)."""
    if not dt:
        return ''
    return dt.replace(tzinfo=timezone.utc).astimezone(_VN_TZ).strftime(fmt)

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


def _get_payment_status_map(reward_requests):
    """Return {request_id: is_paid} for cash-type reward requests.

    'misa_payment_is_paid' is only added by the amis_callback module - trả
    dict rỗng nếu module đó chưa cài để trang portal không lỗi.
    """
    cash_requests = reward_requests.filtered(lambda r: r.request_type == 'cash')
    if not cash_requests or 'misa_payment_is_paid' not in cash_requests._fields:
        return {}
    return {r.id: r.misa_payment_is_paid for r in cash_requests}


def _account_or_legacy_domain(account, root):
    """Domain: bản ghi thuộc CHÍNH tài khoản đang đăng nhập, HOẶC dữ liệu cũ
    (trước khi có tính năng nhiều tài khoản/công ty, account_id còn rỗng)
    thuộc cùng công ty — để không "mất" lịch sử của khách trong lúc chờ
    admin chạy wizard migrate dữ liệu cũ vào tài khoản.
    """
    family_ids = [root.id] + root.child_ids.ids
    return [
        '|',
        ('account_id', '=', account.id),
        '&', ('account_id', '=', False), ('partner_id', 'in', family_ids),
    ]


def _owns_record(rec, account, root):
    """True nếu bản ghi (voucher/reward request) thuộc tài khoản đang đăng
    nhập, hoặc là dữ liệu cũ chưa migrate thuộc cùng công ty (xem
    `_account_or_legacy_domain`)."""
    if rec.account_id:
        return rec.account_id.id == account.id
    return rec.partner_id.id in root._get_loyalty_family_partner_ids()


def _load_account_data(account):
    """Load dashboard data cho 1 tài khoản Portal — điểm đổi thưởng và
    lịch sử/voucher 'của tôi' scope theo CHÍNH tài khoản này (mỗi tài
    khoản có pool điểm đổi thưởng riêng); điểm xếp hạng + hạng thành viên
    vẫn hiển thị theo công ty (cộng dồn từ mọi tài khoản, xem
    `res.partner._compute_loyalty_total_points`).
    """
    root = account.partner_id._get_loyalty_root()
    scope_domain = _account_or_legacy_domain(account, root)
    tiers = request.env['hlv.loyalty.tier'].sudo().search(
        [('active', '=', True)], order='min_points asc'
    )
    program = request.env['hlv.loyalty.program'].sudo().search(
        [('active', '=', True)], limit=1
    )
    # Recent 5 active vouchers + total count (của riêng tài khoản này)
    active_vouchers = request.env['hlv.loyalty.voucher'].sudo().search(
        scope_domain + [('state', '=', 'active')], limit=5
    )
    active_vouchers_count = request.env['hlv.loyalty.voucher'].sudo().search_count(
        scope_domain + [('state', '=', 'active')]
    )
    # Recent 5 history entries + total count (của riêng tài khoản này)
    recent_history = request.env['hlv.loyalty.history'].sudo().search(
        scope_domain, order='date desc', limit=5
    )
    history_count = request.env['hlv.loyalty.history'].sudo().search_count(scope_domain)
    next_tier = None
    if root.loyalty_tier_id:
        next_tier = request.env['hlv.loyalty.tier'].sudo().search([
            ('min_points', '>', root.loyalty_total_points),
            ('active', '=', True),
        ], order='min_points asc', limit=1)
    return {
        'tiers': tiers,
        'program': program,
        'partner': root,
        'active_vouchers': active_vouchers,
        'active_vouchers_count': active_vouchers_count,
        'recent_history': recent_history,
        'history_count': history_count,
        'next_tier': next_tier,
        'masked_phone': _mask_phone(root.phone),
        'masked_email': _mask_email(root.email),
        'exchange_points': account.loyalty_exchange_points,
        'reward_pending_points': account.loyalty_reward_pending_points,
        'exchange_available_points': account.loyalty_exchange_available_points,
        'pending_points': account.loyalty_pending_points,
        'fmt_vn_date': lambda dt: _vn_datetime(dt, '%d Thg %m, %Y'),
        'fmt_vn_time': lambda dt: _vn_datetime(dt, '%H:%M'),
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
        data = _load_account_data(account)
        data['account'] = account
        # Show portal_phone (login phone) in header, not partner.phone
        if account.portal_phone:
            data['masked_phone'] = _mask_phone(account.portal_phone)
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
            data = _load_account_data(account)
            data['account'] = account
            data['phone_error'] = 'Số điện thoại không được để trống.'
            data['show_phone_modal'] = True
            return request.render('hlv_loyalty.loyalty_public_dashboard', data)

        if not re.match(r'^[\d\s\-\+]{7,15}$', new_phone):
            data = _load_account_data(account)
            data['account'] = account
            data['phone_error'] = 'Số điện thoại không hợp lệ.'
            data['show_phone_modal'] = True
            return request.render('hlv_loyalty.loyalty_public_dashboard', data)

        # Update portal_phone (login phone), not partner.phone
        account.sudo().write({'portal_phone': new_phone})
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
            data = _load_account_data(account)
            data['account'] = account
            data['pw_error'] = error
            data['show_pw_modal'] = True
            return request.render('hlv_loyalty.loyalty_public_dashboard', data)

        try:
            account.sudo().set_password(new_password)
        except UserError as e:
            data = _load_account_data(account)
            data['account'] = account
            data['pw_error'] = str(e)
            data['show_pw_modal'] = True
            return request.render('hlv_loyalty.loyalty_public_dashboard', data)

        return request.redirect('/loyalty/dashboard?success=password_changed')

    # ── Full history page ─────────────────────────────────────────────────────

    @http.route('/loyalty/history', type='http', auth='public', website=True,
                sitemap=False)
    def loyalty_history_full(self, **kwargs):
        account = _get_current_account()
        if not account:
            return request.redirect('/loyalty')
        root = account.partner_id._get_loyalty_root()

        # ── Filter params ──────────────────────────────────────────────────
        active_pt = kwargs.get('pt', 'all')   # all | ranking | exchange
        active_st = kwargs.get('st', 'all')   # all | pending | confirmed | cancelled
        if active_pt not in ('all', 'ranking', 'exchange'):
            active_pt = 'all'
        if active_st not in ('all', 'pending', 'confirmed', 'cancelled'):
            active_st = 'all'

        domain = _account_or_legacy_domain(account, root)
        if active_pt != 'all':
            domain.append(('point_type', '=', active_pt))
        if active_st != 'all':
            domain.append(('state', '=', active_st))

        all_history = request.env['hlv.loyalty.history'].sudo().search(
            domain, order='date desc'
        )

        # Với các giao dịch 'redeem' phát sinh từ yêu cầu đổi thưởng của khách
        # (không phải do admin đổi trực tiếp), tìm lại yêu cầu gốc qua
        # history_id để hiện tình trạng thanh toán + link xem chi tiết.
        redeem_history_ids = all_history.filtered(lambda h: h.transaction_type == 'redeem').ids
        reward_requests = request.env['hlv.loyalty.reward.request'].sudo().search([
            ('history_id', 'in', redeem_history_ids),
        ]) if redeem_history_ids else request.env['hlv.loyalty.reward.request']
        request_by_history_id = {rr.history_id.id: rr for rr in reward_requests}

        data = _load_account_data(account)
        data['account'] = account
        if account.portal_phone:
            data['masked_phone'] = _mask_phone(account.portal_phone)
        data['all_history'] = all_history
        data['active_pt'] = active_pt
        data['active_st'] = active_st
        data['request_by_history_id'] = request_by_history_id
        data['payment_status_by_request'] = _get_payment_status_map(reward_requests)
        return request.render('hlv_loyalty.loyalty_portal_history_full', data)

    # ── Reward redemption page ────────────────────────────────────────────

    @http.route('/loyalty/redeem', type='http', auth='public', website=True,
                sitemap=False)
    def loyalty_redeem(self, **kwargs):
        account = _get_current_account()
        if not account:
            return request.redirect('/loyalty')

        active_tab = kwargs.get('tab', 'gift')
        if active_tab not in ('gift', 'cash', 'history'):
            active_tab = 'gift'

        root = account.partner_id._get_loyalty_root()

        program = request.env['hlv.loyalty.program'].sudo().search(
            [('active', '=', True)], limit=1
        )
        packages = request.env['hlv.loyalty.voucher.package'].sudo().search([
            ('active', '=', True),
        ], order='points_required asc')
        my_requests = request.env['hlv.loyalty.reward.request'].sudo().search(
            _account_or_legacy_domain(account, root), order='date_request desc', limit=50,
        )

        data = _load_account_data(account)
        data.update({
            'account': account,
            'active_tab': active_tab,
            'program': program,
            'packages': packages,
            'my_requests': my_requests,
            'payment_status_by_request': _get_payment_status_map(my_requests),
            'success_msg': kwargs.get('success_msg', ''),
            'error_msg': kwargs.get('error_msg', ''),
            'form_vals': {},
        })
        if account.portal_phone:
            data['masked_phone'] = _mask_phone(account.portal_phone)
        return request.render('hlv_loyalty.loyalty_portal_redeem', data)

    # ── Submit gift redemption (auto-processed) ───────────────────────────

    @http.route('/loyalty/redeem/gift', type='http', auth='public', website=True,
                sitemap=False, methods=['POST'])
    def loyalty_redeem_gift(self, **post):
        account = _get_current_account()
        if not account:
            return request.redirect('/loyalty')

        pkg_id = int(post.get('package_id') or 0)
        if not pkg_id:
            return request.redirect('/loyalty/redeem?tab=gift')

        root = account.partner_id._get_loyalty_root()
        pkg = request.env['hlv.loyalty.voucher.package'].sudo().browse(pkg_id)
        if not pkg.exists() or not pkg.active:
            return request.redirect('/loyalty/redeem?tab=gift')

        balance = account.loyalty_exchange_points
        avail = account.loyalty_exchange_available_points
        if avail < pkg.points_required:
            return request.redirect(
                f'/loyalty/redeem?tab=gift&error_msg='
                f'Không đủ điểm khả dụng. Bạn còn {avail} điểm, cần {pkg.points_required} điểm. '
                f'Đang treo {account.loyalty_reward_pending_points} điểm trong yêu cầu chờ xử lý.'
            )

        # Create and immediately process (gift = no admin approval needed)
        rq = request.env['hlv.loyalty.reward.request'].sudo().create({
            'partner_id': root.id,
            'account_id': account.id,
            'request_type': 'gift',
            'package_id': pkg.id,
            'balance_at_request': balance,
            'company_id': request.env.company.id,
        })
        rq.action_done()

        voucher_code = rq.voucher_id.code if rq.voucher_id else ''
        msg = f'Đổi quà thành công! Voucher của bạn: {voucher_code}' if voucher_code else 'Đổi quà thành công!'
        return request.redirect(f'/loyalty/redeem?tab=history&success_msg={msg}')

    # ── Submit cash redemption (pending → admin approves) ─────────────────

    @http.route('/loyalty/redeem/cash', type='http', auth='public', website=True,
                sitemap=False, methods=['POST'])
    def loyalty_redeem_cash(self, **post):
        account = _get_current_account()
        if not account:
            return request.redirect('/loyalty')

        root = account.partner_id._get_loyalty_root()
        balance = account.loyalty_exchange_points
        avail = account.loyalty_exchange_available_points

        points_to_redeem = int(post.get('points_to_redeem') or 0)
        bank_name = (post.get('bank_name') or '').strip()
        account_number = (post.get('account_number') or '').strip()
        account_name = (post.get('account_name') or '').strip()
        customer_note = (post.get('customer_note') or '').strip()

        errors = []
        if points_to_redeem <= 0:
            errors.append('Vui lòng nhập số điểm muốn đổi.')
        elif points_to_redeem > avail:
            errors.append(
                f'Không đủ điểm khả dụng. Bạn còn {avail:,} điểm, yêu cầu {points_to_redeem:,} điểm. '
                f'Đang treo {account.loyalty_reward_pending_points:,} điểm trong yêu cầu chờ xử lý.'
            )
        if not bank_name:
            errors.append('Vui lòng nhập tên ngân hàng.')
        if not account_number:
            errors.append('Vui lòng nhập số tài khoản.')
        if not account_name:
            errors.append('Vui lòng nhập tên chủ tài khoản.')

        if errors:
            # Re-render with errors + form values
            program = request.env['hlv.loyalty.program'].sudo().search(
                [('active', '=', True)], limit=1
            )
            packages = request.env['hlv.loyalty.voucher.package'].sudo().search(
                [('active', '=', True)], order='points_required asc'
            )
            my_requests = request.env['hlv.loyalty.reward.request'].sudo().search(
                _account_or_legacy_domain(account, root), order='date_request desc', limit=50,
            )
            data = _load_account_data(account)
            data.update({
                'account': account,
                'active_tab': 'cash',
                'program': program,
                'packages': packages,
                'my_requests': my_requests,
                'success_msg': '',
                'error_msg': ' | '.join(errors),
                'form_vals': post,
            })
            if account.portal_phone:
                data['masked_phone'] = _mask_phone(account.portal_phone)
            return request.render('hlv_loyalty.loyalty_portal_redeem', data)

        request.env['hlv.loyalty.reward.request'].sudo().create({
            'partner_id': root.id,
            'account_id': account.id,
            'request_type': 'cash',
            'points_to_redeem': points_to_redeem,
            'bank_name': bank_name,
            'account_number': account_number,
            'account_name': account_name,
            'customer_note': customer_note,
            'balance_at_request': balance,
            'company_id': request.env.company.id,
        })
        return request.redirect(
            '/loyalty/redeem?tab=history'
            '&success_msg=Yêu cầu đổi tiền đã được gửi. Chúng tôi sẽ xử lý sớm nhất!'
        )

    @http.route('/loyalty/redeem/request/<int:request_id>/cancel', type='http',
                auth='public', website=True, sitemap=False, methods=['POST'])
    def loyalty_cancel_redeem_request(self, request_id, **post):
        account = _get_current_account()
        if not account:
            return request.redirect('/loyalty')

        root = account.partner_id._get_loyalty_root()
        req = request.env['hlv.loyalty.reward.request'].sudo().browse(request_id)
        if not req.exists() or not _owns_record(req, account, root):
            return request.redirect('/loyalty/redeem?tab=history&error_msg=Không tìm thấy yêu cầu cần hủy.')
        try:
            req.action_cancel()
        except UserError as exc:
            return request.redirect(f'/loyalty/redeem?tab=history&error_msg={exc.args[0]}')

        return request.redirect('/loyalty/redeem?tab=history&success_msg=Yêu cầu đổi thưởng đã được hủy.')

    @http.route('/loyalty/redeem/request/<int:request_id>/update-bank', type='http',
                auth='public', website=True, sitemap=False, methods=['POST'])
    def loyalty_update_redeem_bank(self, request_id, **post):
        account = _get_current_account()
        if not account:
            return request.redirect('/loyalty')

        root = account.partner_id._get_loyalty_root()
        req = request.env['hlv.loyalty.reward.request'].sudo().browse(request_id)
        if not req.exists() or not _owns_record(req, account, root):
            return request.redirect('/loyalty/redeem?tab=history&error_msg=Không tìm thấy yêu cầu cần cập nhật.')
        try:
            req.action_update_bank_info(
                post.get('bank_name'), post.get('account_number'), post.get('account_name'),
            )
        except UserError as exc:
            return request.redirect(f'/loyalty/redeem?tab=history&error_msg={exc.args[0]}')

        return request.redirect('/loyalty/redeem?tab=history&success_msg=Đã cập nhật thông tin nhận tiền.')

    @http.route('/loyalty/redeem/request/<int:request_id>', type='http', auth='public',
                website=True, sitemap=False)
    def loyalty_redeem_request_detail(self, request_id, **kwargs):
        account = _get_current_account()
        if not account:
            return request.redirect('/loyalty')

        root = account.partner_id._get_loyalty_root()
        rq = request.env['hlv.loyalty.reward.request'].sudo().browse(request_id)
        if not rq.exists() or not _owns_record(rq, account, root):
            return request.redirect('/loyalty/redeem?tab=history&error_msg=Không tìm thấy yêu cầu.')

        payment_is_paid = _get_payment_status_map(rq).get(rq.id)

        data = {
            'account': account,
            'partner': root,
            'rq': rq,
            'payment_is_paid': payment_is_paid,
            'success_msg': kwargs.get('success_msg', ''),
            'error_msg': kwargs.get('error_msg', ''),
            'fmt_vn_date': lambda dt: _vn_datetime(dt, '%d Thg %m, %Y'),
            'fmt_vn_time': lambda dt: _vn_datetime(dt, '%H:%M'),
        }
        return request.render('hlv_loyalty.loyalty_portal_request_detail', data)

    @http.route('/loyalty/vouchers', type='http', auth='public', website=True,
                sitemap=False)
    def loyalty_vouchers_full(self, **kwargs):
        account = _get_current_account()
        if not account:
            return request.redirect('/loyalty')
        root = account.partner_id._get_loyalty_root()
        scope_domain = _account_or_legacy_domain(account, root)
        all_vouchers = request.env['hlv.loyalty.voucher'].sudo().search(
            scope_domain + [('state', '=', 'active')]
        )
        inactive_vouchers = request.env['hlv.loyalty.voucher'].sudo().search(
            scope_domain + [('state', 'in', ['used', 'expired', 'cancelled'])]
        )
        data = _load_account_data(account)
        data['account'] = account
        if account.portal_phone:
            data['masked_phone'] = _mask_phone(account.portal_phone)
        data['all_vouchers'] = all_vouchers
        data['inactive_vouchers'] = inactive_vouchers
        return request.render('hlv_loyalty.loyalty_portal_vouchers_full', data)


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
