# -*- coding: utf-8 -*-
import json
import logging
import time

from odoo import fields as odoo_fields, http
from odoo.exceptions import UserError
from odoo.http import request, Response

from odoo.addons.hlv_loyalty.controllers.loyalty_api import LoyaltyExternalAPI, _vn_datetime

_logger = logging.getLogger(__name__)


class LoyaltyAppLoyaltyAPI(LoyaltyExternalAPI):
    """Override LoyaltyExternalAPI từ module hlv_loyalty để:
    1. Scope toàn bộ Điểm (ranking_points, exchange_points, pending_reward_points, exchange_points_available)
       và Hạng thành viên (Tier) theo từng tài khoản Portal (hlv.loyalty.portal.account).
    2. Bổ sung trường `buyer_name` (Tên thu mua) vào dữ liệu trả về cho App.
    3. Lọc Lịch sử điểm (history), Vouchers, Đơn đổi thưởng (redeem requests) theo `account_id`.
    4. Cung cấp route sync version độc lập cho Loyalty Mobile App.
    5. Xử lý toàn bộ CORS và chuẩn hóa bảo mật dữ liệu riêng cho Loyalty App.
    """

    # ── Helpers Override (CORS & Response) ───────────────────────────────────

    @staticmethod
    def _cors_headers():
        return {
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
            'Access-Control-Max-Age': '86400',
        }

    @staticmethod
    def _json_ok(data, status=200):
        return Response(json.dumps(data, default=str),
                        status=status, content_type='application/json',
                        headers=LoyaltyAppLoyaltyAPI._cors_headers())

    @staticmethod
    def _json_err(msg, status=400, **extra):
        body = {'error': msg}
        body.update(extra)
        return Response(json.dumps(body, default=str),
                        status=status, content_type='application/json',
                        headers=LoyaltyAppLoyaltyAPI._cors_headers())


    @classmethod
    def _account_from_portal_phone(cls, partner_id, phone):
        """Tìm partner (root) và account khớp với partner_id & phone."""
        try:
            partner = request.env['res.partner'].sudo().browse(int(partner_id))
        except Exception:
            return None, None, '', cls._json_err('Invalid partner_id', status=400, code='INVALID_PARTNER_ID')
        if not partner.exists():
            return None, None, '', cls._json_err('Khach hang khong ton tai', status=404, code='PARTNER_NOT_FOUND')

        normalized = cls._normalize_vn_phone(phone)
        if not normalized:
            return None, None, '', cls._json_err('Missing phone', status=401, code='MISSING_PHONE')

        root = partner._get_loyalty_root()
        accounts = request.env['hlv.loyalty.portal.account'].sudo().search([
            ('portal_phone', '=', normalized),
            ('active', '=', True),
        ])
        account = accounts.filtered(lambda acc: acc.partner_id._get_loyalty_root().id == root.id)[:1]
        if not account:
            return None, None, normalized, cls._json_err('Missing or invalid partner_id/phone', status=401, code='UNAUTHORIZED')
        return root, account, normalized, None

    @classmethod
    def _account_from_portal_phone_rpc(cls, partner_id, phone):
        """Dành cho JSON-RPC: trả về (root, account, error_dict)."""
        try:
            partner = request.env['res.partner'].sudo().browse(int(partner_id))
        except Exception:
            return None, None, {'error': 'Invalid partner_id', 'code': 'INVALID_PARTNER_ID'}
        if not partner.exists():
            return None, None, {'error': 'Khach hang khong ton tai', 'code': 'PARTNER_NOT_FOUND'}

        normalized = cls._normalize_vn_phone(phone)
        if not normalized:
            return None, None, {'error': 'Missing phone', 'code': 'MISSING_PHONE'}

        root = partner._get_loyalty_root()
        accounts = request.env['hlv.loyalty.portal.account'].sudo().search([
            ('portal_phone', '=', normalized),
            ('active', '=', True),
        ])
        account = accounts.filtered(lambda acc: acc.partner_id._get_loyalty_root().id == root.id)[:1]
        if not account:
            return None, None, {'error': 'Missing or invalid partner_id/phone', 'code': 'UNAUTHORIZED'}
        return root, account, None

    @classmethod
    def _partner_summary_scoped(cls, partner, account=None):
        """Tính summary theo tài khoản (account) nếu có, fallback về partner."""
        tiers_asc = request.env['hlv.loyalty.tier'].sudo().search([], order='min_points asc')
        tiers_desc = request.env['hlv.loyalty.tier'].sudo().search([], order='min_points desc')

        if account:
            pts = account.loyalty_total_points
            exc_pts = account.loyalty_exchange_points
            pending_reward_points = account.loyalty_reward_pending_points
            available_exchange_points = account.loyalty_exchange_available_points
            tier = next((t for t in tiers_desc if pts >= t.min_points), None)
            next_tier = next((t for t in tiers_asc if t.min_points > pts), None)
            buyer_name = account.buyer_name or ''
            username = account.username or ''
            account_id = account.id
            is_default_password = account._verify_password('hlv@2026', account.password_hash)
            has_password = bool(account.password_hash)
        else:
            pts = partner.loyalty_total_points
            exc_pts = partner.loyalty_exchange_points
            pending_reward_points = partner.loyalty_reward_pending_points
            available_exchange_points = partner.loyalty_exchange_available_points
            tier = partner.loyalty_tier_id
            next_tier = next((t for t in tiers_asc if t.min_points > pts), None)
            buyer_name = ''
            username = ''
            account_id = None
            is_default_password = False
            has_password = False

        points_to_next = (next_tier.min_points - pts) if next_tier else 0

        res = {
            'id': partner.id,
            'name': partner.name,
            'phone': (account.portal_phone if account else partner.phone) or '',
            'email': partner.email or '',
            'ranking_points': pts,
            'exchange_points': exc_pts,
            'pending_reward_points': pending_reward_points,
            'exchange_points_available': available_exchange_points,
            'total_points': pts,
            'image_url': cls._partner_image_url(partner),
            'tier': cls._tier_dict(tier),
            'tier_image_url': tier.image_url if tier else '',
            'next_tier': cls._tier_dict(next_tier),
            'next_tier_image_url': next_tier.image_url if next_tier else '',
            'points_to_next': points_to_next,
            'buyer_name': buyer_name,
            'username': username,
            'has_password': has_password,
            'is_default_password': is_default_password,
        }
        if account_id:
            res['account_id'] = account_id
        return res

    @classmethod
    def _partner_lookup_summary(cls, partner, account=None):
        """Dữ liệu tối thiểu & bảo mật cho API tra cứu công khai (trước khi đăng nhập).
        Tuyệt đối không để lộ: điểm thưởng, email, hạng thành viên, người thu mua...
        """
        is_default_password = account._verify_password('hlv@2026', account.password_hash) if account else False
        has_password = bool(account.password_hash) if account else False
        account_id = account.id if account else None

        res = {
            'id': partner.id,
            'name': partner.name or '',
            'phone': (account.portal_phone if account else partner.phone) or '',
            'has_password': has_password,
            'is_default_password': is_default_password,
        }
        if account_id:
            res['account_id'] = account_id
        return res

    # ── Override Endpoints ──────────────────────────────────────────────────

    @http.route('/api/v1/loyalty/partner/lookup', type='http',
                auth='public', methods=['GET', 'POST', 'OPTIONS'], csrf=False, cors='*')
    def lookup_partner(self, **kwargs):
        """GET/POST /api/v1/loyalty/partner/lookup?phone=0901234567"""
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())
        body = self._request_json()
        phone = self._normalize_vn_phone(kwargs.get('phone') or body.get('phone') or '')
        email = (kwargs.get('email') or body.get('email') or '').strip().lower()

        if not phone and not email:
            return self._json_err('Cần truyền phone hoặc email')

        partner_ids = set()
        matched_accounts = {}

        if phone:
            accounts = request.env['hlv.loyalty.portal.account'].sudo().search(
                [('portal_phone', '=', phone), ('active', '=', True)], limit=5
            )
            for acc in accounts:
                partner_ids.add(acc.partner_id.id)
                matched_accounts[acc.partner_id._get_loyalty_root().id] = acc
        elif email:
            partners_by_email = request.env['res.partner'].sudo().search(
                [('email', '=ilike', email)], limit=5
            )
            for p in partners_by_email:
                partner_ids.add(p.id)

        if not partner_ids:
            return self._json_err('Không tìm thấy khách hàng', status=404)

        partners = request.env['res.partner'].sudo().browse(list(partner_ids))
        results = []
        seen = set()
        for p in partners:
            root = p._get_loyalty_root()
            if root.id not in seen:
                seen.add(root.id)
                account = matched_accounts.get(root.id) or self._account_for_root(root, phone)
                summary = self._partner_lookup_summary(root, account=account)
                if phone:
                    summary['phone'] = phone
                results.append(summary)

        if not results:
            return self._json_err('Không tìm thấy khách hàng', status=404)
        return self._json_ok(results if len(results) > 1 else results[0])

    @http.route('/api/v1/loyalty/auth/login', type='http',
                auth='public', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def auth_login(self, **kwargs):
        """POST /api/v1/loyalty/auth/login"""
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())

        body = self._request_json()
        login_input = (kwargs.get('login') or kwargs.get('phone') or body.get('login') or body.get('phone') or '').strip()
        password = (kwargs.get('password') or body.get('password') or '').strip()

        if not login_input:
            return self._json_err('Vui lòng nhập số điện thoại hoặc tên đăng nhập', status=400, code='MISSING_LOGIN')
        if not password:
            return self._json_err('Vui lòng nhập mật khẩu', status=400, code='MISSING_PASSWORD')

        phone_normalized = self._normalize_vn_phone(login_input)
        PortalAccount = request.env['hlv.loyalty.portal.account'].sudo()

        domain = [('active', '=', True)]
        if phone_normalized:
            domain += ['|', ('username', '=', login_input), ('portal_phone', '=', phone_normalized)]
        else:
            domain += [('username', '=', login_input)]

        existing_accounts = PortalAccount.search(domain, limit=1)
        if not existing_accounts:
            return self._json_err('Số điện thoại chưa đăng ký tài khoản loyalty', status=404, code='NOT_REGISTERED')

        account = PortalAccount.authenticate(login_input, password)
        if not account:
            return self._json_err('Mật khẩu không chính xác. Vui lòng kiểm tra lại.', status=401, code='INVALID_PASSWORD')

        root = account.partner_id._get_loyalty_root()
        summary = self._partner_summary_scoped(root, account=account)
        summary['phone'] = account.portal_phone or phone_normalized or login_input
        return self._json_ok(summary)

    @http.route('/api/v1/loyalty/partner/<int:partner_id>', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    def get_partner(self, partner_id, **kwargs):
        """GET /api/v1/loyalty/partner/<id>"""
        root, account, portal_phone, error = self._account_from_portal_phone(partner_id, kwargs.get('phone'))
        if error:
            return error
        summary = self._partner_summary_scoped(root, account=account)
        summary['phone'] = portal_phone

        # Voucher active theo account
        if account:
            voucher_domain = [
                '|',
                ('account_id', '=', account.id),
                '&', ('account_id', '=', False), ('partner_id', '=', root.id),
                ('state', '=', 'active'),
            ]
        else:
            voucher_domain = [('partner_id', '=', root.id), ('state', '=', 'active')]

        vouchers = request.env['hlv.loyalty.voucher'].sudo().search(voucher_domain, order='date_expiry asc')
        summary['active_vouchers'] = [{
            'id': v.id,
            'code': v.code,
            'discount_type': v.discount_type,
            'discount_value': v.discount_value,
            'date_expiry': _vn_datetime(v.date_expiry),
        } for v in vouchers]

        # Lịch sử 10 gần nhất theo account
        if account:
            history_domain = [
                '|',
                ('account_id', '=', account.id),
                '&', ('account_id', '=', False), ('partner_id', 'in', root._get_loyalty_family_partner_ids()),
            ]
        else:
            history_domain = [('partner_id', 'in', root._get_loyalty_family_partner_ids())]

        history = request.env['hlv.loyalty.history'].sudo().search(history_domain, limit=10, order='date desc')
        summary['recent_history'] = [{
            'id': h.id,
            'date': _vn_datetime(h.date),
            'point_amount': h.point_amount,
            'point_type': h.point_type or 'ranking',
            'transaction_type': h.transaction_type,
            'state': h.state,
            'description': h.description or '',
        } for h in history]

        return self._json_ok(summary)

    @http.route('/api/v1/loyalty/partner/<int:partner_id>/history', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    def get_partner_history(self, partner_id, **kwargs):
        """GET /api/v1/loyalty/partner/<id>/history?limit=20&offset=0"""
        root, account, portal_phone, error = self._account_from_portal_phone(partner_id, kwargs.get('phone'))
        if error:
            return error

        limit = min(int(kwargs.get('limit', 20)), 100)
        offset = int(kwargs.get('offset', 0))
        active_pt = kwargs.get('pt') or kwargs.get('point_type') or 'all'
        active_st = kwargs.get('st') or kwargs.get('state') or 'all'
        active_tt = kwargs.get('tt') or kwargs.get('transaction_type') or 'all'

        if active_pt not in ('all', 'ranking', 'exchange'):
            active_pt = 'all'
        if active_st not in ('all', 'pending', 'confirmed', 'cancelled'):
            active_st = 'all'
        if active_tt not in ('all', 'earn', 'redeem', 'return', 'manual'):
            active_tt = 'all'

        if account:
            domain = [
                '|',
                ('account_id', '=', account.id),
                '&', ('account_id', '=', False), ('partner_id', 'in', root._get_loyalty_family_partner_ids()),
            ]
        else:
            domain = [('partner_id', 'in', root._get_loyalty_family_partner_ids())]

        if active_pt != 'all':
            domain.append(('point_type', '=', active_pt))
        if active_st != 'all':
            domain.append(('state', '=', active_st))
        if active_tt != 'all':
            domain.append(('transaction_type', '=', active_tt))

        date_from = (kwargs.get('date_from') or '').strip()
        date_to = (kwargs.get('date_to') or '').strip()
        try:
            if date_from:
                from_dt = odoo_fields.Datetime.to_datetime(
                    date_from if len(date_from) > 10 else f'{date_from} 00:00:00'
                )
                domain.append(('date', '>=', from_dt))
            if date_to:
                to_dt = odoo_fields.Datetime.to_datetime(
                    date_to if len(date_to) > 10 else f'{date_to} 23:59:59'
                )
                domain.append(('date', '<=', to_dt))
        except Exception:
            return self._json_err('Khoảng ngày không hợp lệ', status=400)

        history = request.env['hlv.loyalty.history'].sudo().search(
            domain, limit=limit, offset=offset, order='date desc',
        )
        total = request.env['hlv.loyalty.history'].sudo().search_count(domain)

        total_pts = account.loyalty_total_points if account else root.loyalty_total_points
        exc_pts = account.loyalty_exchange_points if account else root.loyalty_exchange_points
        pending_pts = account.loyalty_reward_pending_points if account else root.loyalty_reward_pending_points
        avail_pts = account.loyalty_exchange_available_points if account else root.loyalty_exchange_available_points

        return self._json_ok({
            'partner_id': root.id,
            'account_id': account.id if account else None,
            'buyer_name': account.buyer_name if account else '',
            'phone': portal_phone,
            'total_points': total_pts,
            'exchange_points': exc_pts,
            'pending_reward_points': pending_pts,
            'exchange_points_available': avail_pts,
            'total_records': total,
            'limit': limit,
            'offset': offset,
            'filters': {
                'point_type': active_pt,
                'state': active_st,
                'transaction_type': active_tt,
                'date_from': date_from,
                'date_to': date_to,
            },
            'records': [{
                'id': h.id,
                'date': _vn_datetime(h.date),
                'point_amount': h.point_amount,
                'point_type': h.point_type or 'ranking',
                'transaction_type': h.transaction_type,
                'state': h.state,
                'description': h.description or '',
            } for h in history],
        })

    @http.route('/api/v1/loyalty/vouchers/<int:partner_id>', type='http',
                auth='public', methods=['GET', 'POST', 'OPTIONS'], csrf=False, cors='*')
    def get_partner_vouchers(self, partner_id, **kwargs):
        """GET/POST /api/v1/loyalty/vouchers/<id>?state=active"""
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())
        body = self._request_json()
        phone = kwargs.get('phone') or body.get('phone')
        state = kwargs.get('state') or body.get('state')
        root, account, portal_phone, error = self._account_from_portal_phone(partner_id, phone)
        if error:
            return error

        if account:
            domain = [
                '|',
                ('account_id', '=', account.id),
                '&', ('account_id', '=', False), ('partner_id', '=', root.id),
            ]
        else:
            domain = [('partner_id', '=', root.id)]

        if state:
            domain.append(('state', '=', state))

        vouchers = request.env['hlv.loyalty.voucher'].sudo().search(
            domain, order='create_date desc'
        )
        return self._json_ok([{
            'id': v.id,
            'code': v.code,
            'state': v.state,
            'discount_type': v.discount_type,
            'discount_value': v.discount_value,
            'max_discount_amount': v.max_discount_amount,
            'date_issued': _vn_datetime(v.date_issued),
            'date_expiry': _vn_datetime(v.date_expiry),
            'package_name': v.package_id.name or '',
            'reward_type': v.reward_type or 'discount',
        } for v in vouchers])

    @http.route('/api/v1/loyalty/redeem/requests', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    def list_redeem_requests(self, **kwargs):
        """GET /api/v1/loyalty/redeem/requests?partner_id=42&state=all"""
        partner_id = kwargs.get('partner_id')
        if not partner_id:
            return self._json_err('Thiếu partner_id', status=400, code='MISSING_PARTNER_ID')

        root, account, portal_phone, error = self._account_from_portal_phone(partner_id, kwargs.get('phone'))
        if error:
            return error

        if account:
            domain = [
                '|',
                ('account_id', '=', account.id),
                '&', ('account_id', '=', False), ('partner_id', 'in', root._get_loyalty_family_partner_ids()),
            ]
        else:
            domain = [('partner_id', 'in', root._get_loyalty_family_partner_ids())]

        state = kwargs.get('state') or 'all'
        if state in ('pending', 'done', 'cancelled'):
            domain.append(('state', '=', state))

        requests = request.env['hlv.loyalty.reward.request'].sudo().search(
            domain, order='date_request desc, id desc'
        )
        exc_pts = account.loyalty_exchange_points if account else root.loyalty_exchange_points
        pending_pts = account.loyalty_reward_pending_points if account else root.loyalty_reward_pending_points
        avail_pts = account.loyalty_exchange_available_points if account else root.loyalty_exchange_available_points

        return self._json_ok({
            'success': True,
            'data': {
                'requests': [self._reward_request_dict(req) for req in requests],
                'exchange_points': exc_pts,
                'pending_reward_points': pending_pts,
                'exchange_points_available': avail_pts,
                'phone': portal_phone,
                'buyer_name': account.buyer_name if account else '',
                'account_id': account.id if account else None,
            },
        })

    @http.route('/api/v1/loyalty/redeem/submit', type='json',
                auth='public', methods=['POST'], csrf=False, cors='*')
    def submit_redeem(self, **kwargs):
        """POST /api/v1/loyalty/redeem/submit"""
        partner_id = kwargs.get('partner_id')
        request_type = kwargs.get('request_type', 'gift')

        if not partner_id:
            return {'error': 'Thiếu partner_id'}
        if request_type not in ('gift', 'cash'):
            return {'error': 'request_type phải là gift hoặc cash'}

        root, account, error = self._account_from_portal_phone_rpc(partner_id, kwargs.get('phone'))
        if error:
            return error

        balance_exchange = account.loyalty_exchange_points if account else root.loyalty_exchange_points
        avail_exchange = account.loyalty_exchange_available_points if account else root.loyalty_exchange_available_points
        pending_reward_points = account.loyalty_reward_pending_points if account else root.loyalty_reward_pending_points
        insufficient_code = 'PENDING_REWARD_POINTS' if pending_reward_points else 'INSUFFICIENT_POINTS'

        vals = {
            'partner_id': root.id,
            'account_id': account.id if account else False,
            'request_type': request_type,
            'balance_at_request': balance_exchange,
            'company_id': request.env.company.id,
        }

        if request_type == 'gift':
            package_id = kwargs.get('package_id')
            if not package_id:
                return {'error': 'Thiếu package_id cho đổi quà'}
            package = request.env['hlv.loyalty.voucher.package'].sudo().browse(int(package_id))
            if not package.exists() or not package.active:
                return {'error': 'Gói quà không tồn tại hoặc đã ngừng'}
            if avail_exchange < package.points_required:
                return {
                    'error': f'Không đủ điểm khả dụng. '
                             f'Cần {package.points_required:,} điểm, bạn còn {avail_exchange:,} điểm. '
                             f'Đang treo {pending_reward_points:,} điểm trong yêu cầu chờ xử lý.',
                    'code': insufficient_code,
                    'exchange_points': balance_exchange,
                    'pending_reward_points': pending_reward_points,
                    'exchange_points_available': avail_exchange,
                }
            vals['package_id'] = package.id

        elif request_type == 'cash':
            points_to_redeem = int(kwargs.get('points_to_redeem') or 0)
            if points_to_redeem <= 0:
                return {'error': 'points_to_redeem phải lớn hơn 0'}
            if avail_exchange < points_to_redeem:
                return {
                    'error': f'Không đủ điểm khả dụng. '
                             f'Cần {points_to_redeem:,} điểm, bạn còn {avail_exchange:,} điểm. '
                             f'Đang treo {pending_reward_points:,} điểm trong yêu cầu chờ xử lý.',
                    'code': insufficient_code,
                    'exchange_points': balance_exchange,
                    'pending_reward_points': pending_reward_points,
                    'exchange_points_available': avail_exchange,
                }
            bank_name = (kwargs.get('bank_name') or '').strip()
            account_number = (kwargs.get('account_number') or '').strip()
            account_name = (kwargs.get('account_name') or '').strip()
            if not bank_name or not account_number or not account_name:
                return {'error': 'Cần điền đầy đủ thông tin ngân hàng (bank_name, account_number, account_name)'}
            vals.update({
                'points_to_redeem': points_to_redeem,
                'bank_name': bank_name,
                'account_number': account_number,
                'account_name': account_name,
                'customer_note': kwargs.get('customer_note') or '',
            })

        try:
            req = request.env['hlv.loyalty.reward.request'].sudo().create(vals)
            if request_type == 'gift':
                req.action_done()
        except UserError as exc:
            return {
                'error': str(exc),
                'code': 'PENDING_REWARD_POINTS',
                'exchange_points': balance_exchange,
                'pending_reward_points': pending_reward_points,
                'exchange_points_available': avail_exchange,
            }

        message = 'Gift redeemed successfully.' if req.request_type == 'gift' else 'Reward request submitted successfully. Please wait for approval.'

        latest_exc = account.loyalty_exchange_points if account else root.loyalty_exchange_points
        latest_pending = account.loyalty_reward_pending_points if account else root.loyalty_reward_pending_points
        latest_avail = account.loyalty_exchange_available_points if account else root.loyalty_exchange_available_points

        return {
            'success': True,
            'request_id': req.id,
            'request_name': req.name,
            'request_type': req.request_type,
            'state': req.state,
            'points_required': req.points_required,
            'cash_value': req.cash_value,
            'voucher_id': req.voucher_id.id if req.voucher_id else None,
            'voucher_code': req.voucher_id.code if req.voucher_id else '',
            'exchange_points': latest_exc,
            'pending_reward_points': latest_pending,
            'exchange_points_available': latest_avail,
            'exchange_points_remaining': max(latest_avail, 0),
            'message': message,
        }

    # ── Version Sync Endpoint (Độc lập cho Loyalty Mobile App) ──────────────

    @http.route([
        '/api/v1/loyalty/sync/version',
        '/api/v1/zalo/sync/version',
    ], type='http', auth='public', methods=['GET', 'POST', 'OPTIONS'], csrf=False, cors='*')
    def loyalty_sync_version(self, **kwargs):
        """GET /api/v1/loyalty/sync/version hoặc /api/v1/zalo/sync/version"""
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())
        try:
            Param = request.env['ir.config_parameter'].sudo()
            forced_loy = Param.get_param('zalo_miniapp_forced_loyalty_version', '')
            forced_ban = Param.get_param('zalo_miniapp_forced_banner_version', '')

            timestamps = []
            for model, domain in (
                ('hlv.loyalty.tier', []),
                ('hlv.loyalty.voucher.package', [('active', '=', True)]),
                ('hlv.loyalty.program', [('active', '=', True)]),
                ('hlv.loyalty.banner', [('active', '=', True)]),
            ):
                if model in request.env:
                    try:
                        rec = request.env[model].sudo().search(domain, order='write_date desc, id desc', limit=1)
                        if rec and (rec.write_date or rec.create_date):
                            wdate = rec.write_date or rec.create_date
                            timestamps.append(int(odoo_fields.Datetime.to_datetime(wdate).timestamp()))
                    except Exception as e:
                        _logger.warning('Error calculating %s max write_date: %s', model, e)

            loyalty_ts = max(timestamps) if timestamps else int(time.time())
            if forced_loy and forced_loy.isdigit():
                loyalty_ts = max(loyalty_ts, int(forced_loy))

            banner_ts = loyalty_ts
            if forced_ban and forced_ban.isdigit():
                banner_ts = int(forced_ban)

            data = {
                'loyalty_version': str(loyalty_ts),
                'banner_version': str(banner_ts),
                'catalog_version': str(loyalty_ts),
                'timestamp': int(time.time()),
            }
            return self._json_ok({'success': True, 'data': data, **data})
        except Exception as e:
            _logger.exception('loyalty_sync_version error: %s', e)
            return self._json_err(str(e), status=500)

    # ── Full Overrides for App Endpoints ─────────────────────────────────────

    @http.route('/api/v1/loyalty/tiers/<int:tier_id>/image', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def tier_image(self, tier_id, **kwargs):
        tier = request.env['hlv.loyalty.tier'].sudo().with_context(bin_size=False).browse(tier_id)
        if not tier.exists():
            return Response(status=404, response='Tier not found', content_type='text/plain; charset=utf-8')
        return self._image_response(tier.tier_image)

    @http.route('/api/v1/loyalty/partners/<int:partner_id>/image', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def partner_image(self, partner_id, **kwargs):
        partner = request.env['res.partner'].sudo().with_context(bin_size=False).browse(partner_id)
        if not partner.exists():
            return Response(status=404, response='Partner not found', content_type='text/plain; charset=utf-8')
        return self._image_response(partner.image_1920 if 'image_1920' in partner._fields else None)

    @http.route('/api/v1/loyalty/tiers', type='http',
                auth='public', methods=['GET', 'POST', 'OPTIONS'], csrf=False, cors='*')
    def list_tiers(self, **kwargs):
        """GET/POST /api/v1/loyalty/tiers"""
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())
        tiers = request.env['hlv.loyalty.tier'].sudo().search([], order='min_points asc')
        return self._json_ok([self._tier_dict(t) for t in tiers])

    @http.route('/api/v1/loyalty/program/config', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    def get_program_config(self, **kwargs):
        """GET /api/v1/loyalty/program/config"""
        program = request.env['hlv.loyalty.program'].sudo().search(
            [('active', '=', True)], limit=1
        )
        if not program:
            return self._json_err('Chưa có chương trình loyalty', status=404)
        return self._json_ok({
            'cash_rate_per_point': program.cash_rate_per_point,
            'voucher_validity_days': program.voucher_validity_days,
            'ranking_desc': program.portal_ranking_desc or '',
            'exchange_desc': program.portal_exchange_desc or '',
        })

    @http.route('/api/v1/loyalty/redeem/packages', type='http',
                auth='public', methods=['GET', 'POST', 'OPTIONS'], csrf=False, cors='*')
    def list_redeem_packages(self, **kwargs):
        """GET/POST /api/v1/loyalty/redeem/packages"""
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())
        packages = request.env['hlv.loyalty.voucher.package'].sudo().search(
            [('active', '=', True)], order='points_required asc'
        )
        return self._json_ok([{
            'id': p.id,
            'name': p.name,
            'points_required': p.points_required,
            'reward_type': p.reward_type,
            'discount_type': p.discount_type,
            'discount_value': p.discount_value,
            'max_discount_amount': p.max_discount_amount,
            'min_order_amount': p.min_order_amount,
            'validity_days': p.validity_days,
            'gift_product_id': p.gift_product_id.id if p.gift_product_id else None,
            'gift_product_name': p.gift_product_id.display_name if p.gift_product_id else '',
            'gift_product_code': p.gift_product_id.default_code or '' if p.gift_product_id else '',
            # Voucher packages do not define a ``state`` field; availability
            # is represented by the ``active`` flag used in the search domain.
            'state': 'available',
        } for p in packages])

    @http.route('/api/v1/loyalty/voucher/validate', type='json',
                auth='public', methods=['POST'], csrf=False, cors='*')
    def validate_voucher(self, **kwargs):
        """POST /api/v1/loyalty/voucher/validate"""
        code = (kwargs.get('code') or '').strip().upper()
        partner_id = kwargs.get('partner_id')
        order_amount = float(kwargs.get('order_amount') or 0.0)

        if not code:
            return {'valid': False, 'error': 'Vui lòng nhập mã voucher', 'code': 'MISSING_CODE'}

        voucher = request.env['hlv.loyalty.voucher'].sudo().search([
            ('code', '=', code),
            ('active', '=', True),
        ], limit=1)

        if not voucher:
            return {'valid': False, 'error': 'Mã voucher không tồn tại hoặc đã bị vô hiệu', 'code': 'VOUCHER_NOT_FOUND'}

        account = None
        if partner_id and kwargs.get('phone'):
            root, account, err = self._account_from_portal_phone_rpc(partner_id, kwargs.get('phone'))
            if err:
                return {'valid': False, 'error': err.get('error', 'Lỗi xác thực'), 'code': err.get('code', 'UNAUTHORIZED')}
            if voucher.partner_id.id != root.id:
                return {'valid': False, 'error': 'Voucher không thuộc về khách hàng này', 'code': 'PARTNER_MISMATCH'}
            if hasattr(voucher, 'portal_account_id') and voucher.portal_account_id and account and voucher.portal_account_id.id != account.id:
                return {'valid': False, 'error': 'Voucher không thuộc về tài khoản này', 'code': 'ACCOUNT_MISMATCH'}

        is_valid, reason = voucher.is_valid_for_order(order_amount=order_amount)
        if not is_valid:
            return {'valid': False, 'error': reason, 'code': 'VOUCHER_INVALID'}

        discount = voucher.compute_discount(order_amount)
        return {
            'valid': True,
            'voucher': {
                'id': voucher.id,
                'code': voucher.code,
                'discount_type': voucher.discount_type,
                'discount_value': voucher.discount_value,
                'estimated_discount': discount,
                'date_expiry': _vn_datetime(voucher.date_expiry),
                'partner_id': voucher.partner_id.id,
                'partner_name': voucher.partner_id.name,
            },
        }

    @http.route('/api/v1/loyalty/account/change-password', type='json',
                auth='public', methods=['POST'], csrf=False, cors='*')
    def change_password(self, **kwargs):
        """POST /api/v1/loyalty/account/change-password"""
        partner_id = kwargs.get('partner_id')
        if not partner_id:
            return {'error': 'Thiếu partner_id', 'code': 'MISSING_PARTNER_ID'}

        root, account, error = self._account_from_portal_phone_rpc(partner_id, kwargs.get('phone'))
        if error:
            return error

        old_password = (kwargs.get('old_password') or '').strip()
        new_password = (kwargs.get('new_password') or '').strip()
        confirm_password = (kwargs.get('confirm_password') or '').strip()

        if not old_password or not new_password or not confirm_password:
            return {'error': 'Vui lòng điền đầy đủ thông tin', 'code': 'MISSING_FIELDS'}
        if not account._verify_password(old_password, account.password_hash):
            return {'error': 'Mật khẩu hiện tại không đúng', 'code': 'INVALID_OLD_PASSWORD'}
        if new_password != confirm_password:
            return {'error': 'Mật khẩu mới và xác nhận không khớp', 'code': 'PASSWORD_MISMATCH'}
        if len(new_password) < 6:
            return {'error': 'Mật khẩu mới phải có ít nhất 6 ký tự', 'code': 'PASSWORD_TOO_SHORT'}

        try:
            account.sudo().set_password(new_password)
        except UserError as exc:
            return {'error': str(exc), 'code': 'CHANGE_PASSWORD_FAILED'}

        return {'success': True, 'message': 'Đổi mật khẩu thành công.'}

    @http.route('/api/v1/loyalty/account/change-phone', type='json',
                auth='public', methods=['POST'], csrf=False, cors='*')
    def change_phone(self, **kwargs):
        """POST /api/v1/loyalty/account/change-phone"""
        partner_id = kwargs.get('partner_id')
        if not partner_id:
            return {'error': 'Thiếu partner_id', 'code': 'MISSING_PARTNER_ID'}

        root, account, error = self._account_from_portal_phone_rpc(partner_id, kwargs.get('phone'))
        if error:
            return error

        new_phone = (kwargs.get('new_phone') or '').strip()
        normalized_new = self._normalize_vn_phone(new_phone)
        if not normalized_new:
            return {'error': 'Số điện thoại mới không hợp lệ', 'code': 'INVALID_PHONE'}

        exists = request.env['hlv.loyalty.portal.account'].sudo().search([
            ('portal_phone', '=', normalized_new),
            ('id', '!=', account.id),
            ('active', '=', True),
        ], limit=1)
        if exists:
            return {'error': 'Số điện thoại này đã được sử dụng bởi tài khoản khác', 'code': 'PHONE_IN_USE'}

        try:
            account.sudo().write({'portal_phone': normalized_new})
        except Exception as exc:
            return {'error': str(exc), 'code': 'CHANGE_PHONE_FAILED'}

        return {'success': True, 'message': 'Đổi số điện thoại thành công.', 'phone': normalized_new}
