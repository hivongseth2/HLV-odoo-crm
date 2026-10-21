# -*- coding: utf-8 -*-
import json
import logging
import time

from odoo import fields as odoo_fields, http
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


    @http.route('/api/v1/loyalty/auth/login', type='http',
                auth='public', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def auth_login(self, **kwargs):
        """POST /api/v1/loyalty/auth/login"""
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())
        limited = self._login_rate_limited()
        if limited:
            return limited

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
        # Không biết ai đang xem nên chỉ trả gói mở cho mọi người và còn suất.
        packages = request.env['hlv.loyalty.voucher.package'].sudo().search(
            [('active', '=', True)], order='points_required asc'
        )._filter_available_for_account()
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


