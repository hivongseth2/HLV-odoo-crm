# -*- coding: utf-8 -*-
import base64
import json
import logging
import re
import requests
from datetime import timedelta, timezone
from odoo import fields as odoo_fields, http
from odoo.exceptions import UserError
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


def _vn_datetime(value):
    if not value:
        return None
    dt = odoo_fields.Datetime.to_datetime(value)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=7))).replace(microsecond=0).isoformat()


class LoyaltyAPIController(http.Controller):
    """API Controller cho tích hợp App Mobile / Website bên ngoài."""

    @staticmethod
    def _normalize_vn_phone(phone):
        if not phone:
            return ''
        digits = ''.join(ch for ch in str(phone).strip() if ch.isdigit())
        if digits.startswith('84'):
            digits = '0' + digits[2:]
        return digits

    def _json_response_error(self, message, status=400, code=None):
        payload = {'error': message}
        if code:
            payload['code'] = code
        return Response(json.dumps(payload), status=status, content_type='application/json')

    def _partner_from_portal_phone_http(self, partner_id, phone):
        try:
            partner = request.env['res.partner'].sudo().browse(int(partner_id))
        except Exception:
            return None, '', self._json_response_error('Invalid partner_id', status=400, code='INVALID_PARTNER_ID')
        if not partner.exists():
            return None, '', self._json_response_error('Khach hang khong ton tai', status=404, code='PARTNER_NOT_FOUND')

        normalized = self._normalize_vn_phone(phone)
        if not normalized:
            return None, '', self._json_response_error('Missing phone', status=401, code='MISSING_PHONE')

        root = partner._get_loyalty_root()
        accounts = request.env['hlv.loyalty.portal.account'].sudo().search([
            ('portal_phone', '=', normalized),
            ('active', '=', True),
        ])
        account = accounts.filtered(lambda acc: acc.partner_id._get_loyalty_root().id == root.id)[:1]
        if not account:
            return None, normalized, self._json_response_error('Missing or invalid partner_id/phone', status=401, code='UNAUTHORIZED')
        return root, normalized, None

    def _partner_from_portal_phone_rpc(self, partner_id, phone):
        try:
            partner = request.env['res.partner'].sudo().browse(int(partner_id))
        except Exception:
            return None, {'error': 'Invalid partner_id', 'code': 'INVALID_PARTNER_ID'}
        if not partner.exists():
            return None, {'error': 'Khach hang khong ton tai', 'code': 'PARTNER_NOT_FOUND'}

        normalized = self._normalize_vn_phone(phone)
        if not normalized:
            return None, {'error': 'Missing phone', 'code': 'MISSING_PHONE'}

        root = partner._get_loyalty_root()
        accounts = request.env['hlv.loyalty.portal.account'].sudo().search([
            ('portal_phone', '=', normalized),
            ('active', '=', True),
        ])
        account = accounts.filtered(lambda acc: acc.partner_id._get_loyalty_root().id == root.id)[:1]
        if not account:
            return None, {'error': 'Missing or invalid partner_id/phone', 'code': 'UNAUTHORIZED'}
        return root, None

    @http.route('/api/loyalty/points/<int:partner_id>', type='http',
                auth='user', methods=['GET'], csrf=False)
    def get_partner_points(self, partner_id, **kwargs):
        """Lấy số điểm hiện tại của khách hàng.

        GET /api/loyalty/points/<partner_id>
        """
        root, portal_phone, error = self._partner_from_portal_phone_http(partner_id, kwargs.get('phone'))
        if error:
            return error
        return Response(
            json.dumps({
                'partner_id': root.id,
                'partner_name': root.name,
                'phone': portal_phone,
                'total_points': root.loyalty_total_points,
            }),
            status=200, content_type='application/json',
        )

    @http.route('/api/loyalty/history/<int:partner_id>', type='http',
                auth='user', methods=['GET'], csrf=False)
    def get_partner_history(self, partner_id, **kwargs):
        """Lấy lịch sử điểm của khách hàng.

        GET /api/loyalty/history/<partner_id>?limit=20&offset=0
        """
        root, portal_phone, error = self._partner_from_portal_phone_http(partner_id, kwargs.get('phone'))
        if error:
            return error

        limit = min(int(kwargs.get('limit', 20)), 100)
        offset = int(kwargs.get('offset', 0))

        history_records = request.env['hlv.loyalty.history'].sudo().search(
            [('partner_id', 'in', root._get_loyalty_family_partner_ids())],
            limit=limit, offset=offset, order='date desc',
        )
        data = []
        for rec in history_records:
            data.append({
                'id': rec.id,
                'date': _vn_datetime(rec.date),
                'point_amount': rec.point_amount,
                'transaction_type': rec.transaction_type,
                'description': rec.description or '',
                'company': rec.company_id.name or '',
            })
        return Response(
            json.dumps({
                'partner_id': root.id,
                'phone': portal_phone,
                'total_points': root.loyalty_total_points,
                'records': data,
            }),
            status=200, content_type='application/json',
        )

    @http.route('/api/loyalty/vouchers/<int:partner_id>', type='http',
                auth='user', methods=['GET'], csrf=False)
    def get_partner_vouchers(self, partner_id, **kwargs):
        """Lấy danh sách Voucher của khách hàng.

        GET /api/loyalty/vouchers/<partner_id>?state=active
        """
        root, portal_phone, error = self._partner_from_portal_phone_http(partner_id, kwargs.get('phone'))
        if error:
            return error

        domain = [('partner_id', '=', root.id)]
        state_filter = kwargs.get('state')
        if state_filter:
            domain.append(('state', '=', state_filter))

        vouchers = request.env['hlv.loyalty.voucher'].sudo().search(domain, order='create_date desc')
        data = []
        for v in vouchers:
            data.append({
                'id': v.id,
                'code': v.code,
                'state': v.state,
                'discount_type': v.discount_type,
                'discount_value': v.discount_value,
                'max_discount_amount': v.max_discount_amount,
                'date_issued': _vn_datetime(v.date_issued),
                'date_expiry': _vn_datetime(v.date_expiry),
                'package_name': v.package_id.name or '',
            })
        return Response(
            json.dumps({
                'partner_id': root.id,
                'phone': portal_phone,
                'vouchers': data,
            }),
            status=200, content_type='application/json',
        )

    @http.route('/api/loyalty/redeem', type='json',
                auth='user', methods=['POST'], csrf=False)
    def redeem_voucher(self, **kwargs):
        """Đổi điểm lấy Voucher từ bên ngoài.

        POST /api/loyalty/redeem
        Body: {"partner_id": 1, "package_id": 1}
        """
        partner_id = kwargs.get('partner_id')
        package_id = kwargs.get('package_id')

        if not partner_id or not package_id:
            return {'error': 'Thiếu partner_id hoặc package_id'}

        root, error = self._partner_from_portal_phone_rpc(partner_id, kwargs.get('phone'))
        if error:
            return error

        package = request.env['hlv.loyalty.voucher.package'].sudo().browse(int(package_id))
        if not package.exists() or not package.active:
            return {'error': 'Gói Voucher không tồn tại hoặc đã ngừng'}

        available_points = root.loyalty_exchange_available_points
        if available_points < package.points_required:
            return {
                'error': (
                    f'Không đủ điểm khả dụng. Cần {package.points_required}, '
                    f'còn {available_points}. Đang treo {root.loyalty_reward_pending_points} điểm.'
                ),
            }

        # Tạo wizard context và thực hiện đổi 123
        validity_days = package._get_validity_days()
        date_expiry = odoo_fields.Datetime.now() + timedelta(days=validity_days)

        voucher = request.env['hlv.loyalty.voucher'].sudo().create({
            'partner_id': root.id,
            'package_id': package.id,
            'date_expiry': date_expiry,
        })

        request.env['hlv.loyalty.history'].sudo().create({
            'partner_id': root.id,
            'point_amount': -package.points_required,
            'point_type': 'exchange',
            'transaction_type': 'redeem',
            'state': 'confirmed',
            'description': f'Đổi Voucher [{package.name}] - Mã: {voucher.code} (API)',
            'voucher_id': voucher.id,
            'company_id': request.env.company.id,
        })
        root.invalidate_recordset([
            'loyalty_exchange_points',
            'loyalty_reward_pending_points',
            'loyalty_exchange_available_points',
        ])

        return {
            'success': True,
            'voucher': {
                'code': voucher.code,
                'discount_type': voucher.discount_type,
                'discount_value': voucher.discount_value,
                'date_expiry': _vn_datetime(date_expiry),
            },
            'remaining_points': root.loyalty_exchange_points,
            'exchange_points_available': root.loyalty_exchange_available_points,
            'pending_reward_points': root.loyalty_reward_pending_points,
        }

    @http.route('/api/loyalty/validate-voucher', type='json',
                auth='user', methods=['POST'], csrf=False)
    def validate_voucher(self, **kwargs):
        """Kiểm tra tính hợp lệ của mã Voucher.

        POST /api/loyalty/validate-voucher
        Body: {"code": "VHQ-A8F2K9", "partner_id": 1, "order_amount": 500000}
        """
        code = (kwargs.get('code') or '').strip().upper()
        partner_id = kwargs.get('partner_id')
        order_amount = float(kwargs.get('order_amount', 0))

        if not code:
            return {'valid': False, 'error': 'Thiếu mã Voucher'}

        root = None
        if partner_id:
            root, error = self._partner_from_portal_phone_rpc(partner_id, kwargs.get('phone'))
            if error:
                return {'valid': False, 'error': error.get('error'), 'code': error.get('code')}

        voucher = request.env['hlv.loyalty.voucher'].sudo().search([
            ('code', '=', code),
        ], limit=1)

        if not voucher:
            return {'valid': False, 'error': 'Mã Voucher không tồn tại'}

        if voucher.state != 'active':
            return {'valid': False, 'error': f'Voucher đang ở trạng thái: {voucher.state}'}

        if voucher.date_expiry and voucher.date_expiry < odoo_fields.Datetime.now():
            return {'valid': False, 'error': 'Voucher đã hết hạn'}

        if root and voucher.partner_id.id not in root._get_loyalty_family_partner_ids():
            return {'valid': False, 'error': 'Voucher không thuộc sở hữu của khách hàng này'}

        if voucher.min_order_amount > 0 and order_amount < voucher.min_order_amount:
            return {
                'valid': False,
                'error': f'Đơn hàng cần tối thiểu {voucher.min_order_amount:,.0f} VNĐ',
            }

        discount = voucher.compute_discount_amount(order_amount) if order_amount > 0 else 0

        return {
            'valid': True,
            'voucher': {
                'code': voucher.code,
                'discount_type': voucher.discount_type,
                'discount_value': voucher.discount_value,
                'estimated_discount': discount,
                'date_expiry': _vn_datetime(voucher.date_expiry),
            },
        }


# ---------------------------------------------------------------------------
# External API — dùng API Key (Authorization: Bearer <key>)
# Tạo key tại: Settings → Technical → API Keys
# ---------------------------------------------------------------------------

class LoyaltyExternalAPI(http.Controller):
    """API công khai cho App Mobile / hệ thống bên ngoài.

    Authentication: API Key
    Header: Authorization: Bearer <api_key>
    """

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _cors_headers():
        headers = {
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
            'Access-Control-Max-Age': '86400',
        }
        has_route_cors = False
        try:
            if hasattr(request, "endpoint") and request.endpoint and hasattr(request.endpoint, "routing"):
                has_route_cors = bool(request.endpoint.routing.get("cors"))
        except Exception:
            pass

        if not has_route_cors:
            headers['Access-Control-Allow-Origin'] = '*'
        return headers

    @staticmethod
    def _json_ok(data, status=200):
        return Response(json.dumps(data, default=str),
                        status=status, content_type='application/json',
                        headers=LoyaltyExternalAPI._cors_headers())

    @staticmethod
    def _json_err(msg, status=400, **extra):
        body = {'error': msg}
        body.update(extra)
        return Response(json.dumps(body, default=str),
                        status=status, content_type='application/json',
                        headers=LoyaltyExternalAPI._cors_headers())

    @staticmethod
    def _request_json():
        raw = request.httprequest.data or b'{}'
        try:
            return json.loads(raw.decode('utf-8')) if raw else {}
        except Exception:
            return {}

    @staticmethod
    def _mask_secret(value, keep=6):
        value = str(value or '')
        if not value:
            return ''
        if len(value) <= keep * 2:
            return value[:2] + '***'
        return value[:keep] + '...' + value[-keep:]

    @staticmethod
    def _normalize_vn_phone(phone):
        if not phone:
            return ''
        digits = ''.join(ch for ch in str(phone).strip() if ch.isdigit())
        if digits.startswith('84'):
            digits = '0' + digits[2:]
        return digits

    def _partner_from_portal_phone(self, partner_id, phone):
        try:
            partner = request.env['res.partner'].sudo().browse(int(partner_id))
        except Exception:
            return None, '', self._json_err('Invalid partner_id', status=400, code='INVALID_PARTNER_ID')
        if not partner.exists():
            return None, '', self._json_err('Khach hang khong ton tai', status=404, code='PARTNER_NOT_FOUND')

        normalized = self._normalize_vn_phone(phone)
        if not normalized:
            return None, '', self._json_err('Missing phone', status=401, code='MISSING_PHONE')

        root = partner._get_loyalty_root()
        accounts = request.env['hlv.loyalty.portal.account'].sudo().search([
            ('portal_phone', '=', normalized),
            ('active', '=', True),
        ])
        account = accounts.filtered(lambda acc: acc.partner_id._get_loyalty_root().id == root.id)[:1]
        if not account:
            return None, normalized, self._json_err('Missing or invalid partner_id/phone', status=401, code='UNAUTHORIZED')
        return root, normalized, None

    def _partner_from_portal_phone_rpc(self, partner_id, phone):
        try:
            partner = request.env['res.partner'].sudo().browse(int(partner_id))
        except Exception:
            return None, {'error': 'Invalid partner_id', 'code': 'INVALID_PARTNER_ID'}
        if not partner.exists():
            return None, {'error': 'Khach hang khong ton tai', 'code': 'PARTNER_NOT_FOUND'}

        normalized = self._normalize_vn_phone(phone)
        if not normalized:
            return None, {'error': 'Missing phone', 'code': 'MISSING_PHONE'}

        root = partner._get_loyalty_root()
        accounts = request.env['hlv.loyalty.portal.account'].sudo().search([
            ('portal_phone', '=', normalized),
            ('active', '=', True),
        ])
        account = accounts.filtered(lambda acc: acc.partner_id._get_loyalty_root().id == root.id)[:1]
        if not account:
            return None, {'error': 'Missing or invalid partner_id/phone', 'code': 'UNAUTHORIZED'}
        return root, None

    @staticmethod
    def _guess_image_mimetype(raw_bytes):
        if raw_bytes.startswith(b'\xff\xd8\xff'):
            return 'image/jpeg'
        if raw_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'image/png'
        if raw_bytes.startswith(b'GIF87a') or raw_bytes.startswith(b'GIF89a'):
            return 'image/gif'
        if raw_bytes.startswith(b'RIFF') and raw_bytes[8:12] == b'WEBP':
            return 'image/webp'
        return 'application/octet-stream'

    @staticmethod
    def _image_response(encoded_image, status_not_found='Không có ảnh'):
        if not encoded_image:
            return Response(status=404, response=status_not_found, content_type='text/plain; charset=utf-8')
        try:
            if isinstance(encoded_image, str):
                encoded_image = encoded_image.strip()
                if ',' in encoded_image and encoded_image.startswith('data:'):
                    encoded_image = encoded_image.split(',', 1)[1]
            raw = base64.b64decode(encoded_image)
        except Exception:
            return Response(status=404, response='Ảnh không hợp lệ', content_type='text/plain; charset=utf-8')
        return Response(raw, status=200, content_type=LoyaltyExternalAPI._guess_image_mimetype(raw))

    @staticmethod
    def _tier_dict(tier):
        if not tier:
            return None
        return {
            'id': tier.id,
            'name': tier.name,
            'min_points': tier.min_points,
            'max_points': tier.max_points or None,
            'color': tier.color,
            'badge_color': tier.badge_color,
            'image_url': tier.image_url,
            'icon': tier.icon,
            'description': tier.description or '',
            'benefits': [b.name for b in tier.benefit_ids],
        }

    @staticmethod
    def _partner_image_url(partner):
        if not partner:
            return ''
        if 'image_1920' in partner._fields and getattr(partner, 'image_1920', None):
            return f'/api/v1/loyalty/partners/{partner.id}/image'
        return ''

    @staticmethod
    def _partner_summary(partner):
        tiers = request.env['hlv.loyalty.tier'].sudo().search([], order='min_points asc')
        tier = partner.loyalty_tier_id
        pts = partner.loyalty_total_points
        exc_pts = partner.loyalty_exchange_points
        pending_reward_points = partner.loyalty_reward_pending_points
        available_exchange_points = partner.loyalty_exchange_available_points
        # tiers sorted asc — next tier là tier đầu tiên có min_points > pts
        next_tier = next((t for t in tiers if t.min_points > pts), None)
        return {
            'id': partner.id,
            'name': partner.name,
            'phone': partner.phone or '',
            'email': partner.email or '',
            'ranking_points': pts,
            'exchange_points': exc_pts,
            'pending_reward_points': pending_reward_points,
            'exchange_points_available': available_exchange_points,
            # backward-compat alias
            'total_points': pts,
            'image_url': LoyaltyExternalAPI._partner_image_url(partner),
            'tier': LoyaltyExternalAPI._tier_dict(tier),
            'tier_image_url': tier.image_url if tier else '',
            'next_tier': LoyaltyExternalAPI._tier_dict(next_tier),
            'next_tier_image_url': next_tier.image_url if next_tier else '',
            'points_to_next': (next_tier.min_points - pts) if next_tier else 0,
        }

    @staticmethod
    def _account_for_root(root, phone=None):
        """Tìm tài khoản loyalty của root partner (ưu tiên khớp phone)."""
        Account = request.env['hlv.loyalty.portal.account'].sudo()
        if phone:
            acc = Account.search([('portal_phone', '=', phone), ('active', '=', True)], limit=1)
            if acc:
                return acc[0]
        acc = Account.search([('partner_id', '=', root.id), ('active', '=', True)], limit=1)
        return acc[0] if acc else None

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

    # ── Endpoints ────────────────────────────────────────────────────────────

    @http.route('/api/v1/loyalty/tiers', type='http',
                auth='public', methods=['GET', 'POST', 'OPTIONS'], csrf=False, cors='*')
    def list_tiers(self, **kwargs):
        """GET/POST /api/v1/loyalty/tiers
        Trả về danh sách hạng thành viên kèm ảnh và quyền lợi.
        """
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())
        tiers = request.env['hlv.loyalty.tier'].sudo().search([], order='min_points asc')
        return self._json_ok([self._tier_dict(t) for t in tiers])

    @http.route('/api/v1/loyalty/partner/lookup', type='http',
                auth='public', methods=['GET', 'POST', 'OPTIONS'], csrf=False, cors='*')
    def lookup_partner(self, **kwargs):
        """GET/POST /api/v1/loyalty/partner/lookup?phone=0901234567
           GET/POST /api/v1/loyalty/partner/lookup?email=abc@example.com

        Tìm khách hàng theo SĐT hoặc email, trả về điểm + hạng.
        """
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())
        body = self._request_json()
        phone = self._normalize_vn_phone(kwargs.get('phone') or body.get('phone') or '')
        email = (kwargs.get('email') or body.get('email') or '').strip().lower()

        if not phone and not email:
            return self._json_err('Cần truyền phone hoặc email')

        partner_ids = set()

        if phone:
            # Chỉ tìm qua portal_phone (đã chuẩn hóa)
            accounts = request.env['hlv.loyalty.portal.account'].sudo().search(
                [('portal_phone', '=', phone), ('active', '=', True)], limit=5
            )
            for acc in accounts:
                partner_ids.add(acc.partner_id.id)
        elif email:
            partners_by_email = request.env['res.partner'].sudo().search(
                [('email', '=ilike', email)], limit=5
            )
            for p in partners_by_email:
                partner_ids.add(p.id)

        if not partner_ids:
            return self._json_err('Không tìm thấy khách hàng', status=404)

        partners = request.env['res.partner'].sudo().browse(list(partner_ids))
        # Ưu tiên commercial_partner_id (root)
        results = []
        seen = set()
        for p in partners:
            root = p._get_loyalty_root()
            if root.id not in seen:
                seen.add(root.id)
                summary = self._partner_summary(root)
                if phone:
                    summary['phone'] = phone
                # Bổ sung thông tin tài khoản để app phân luồng đăng nhập
                account = self._account_for_root(root, phone)
                if account:
                    summary['account_id'] = account.id
                    summary['username'] = account.username
                    summary['has_password'] = bool(account.password_hash)
                    summary['is_default_password'] = account._verify_password('hlv@2026', account.password_hash)
                results.append(summary)

        if not results:
            return self._json_err('Không tìm thấy khách hàng', status=404)
        return self._json_ok(results if len(results) > 1 else results[0])

    @http.route('/api/v1/loyalty/auth/login', type='http',
                auth='public', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def auth_login(self, **kwargs):
        """POST /api/v1/loyalty/auth/login
        Body JSON: {"phone": "0901234567", "password": "..."} or {"login": "...", "password": "..."}

        Xác thực tài khoản Portal (hlv.loyalty.portal.account) bằng SĐT/Username + Mật khẩu.
        """
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
        summary = self._partner_summary(root)
        summary['phone'] = account.portal_phone or phone_normalized or login_input
        summary['account_id'] = account.id
        summary['username'] = account.username
        if account.buyer_name:
            summary['buyer_name'] = account.buyer_name

        is_default = account._verify_password('hlv@2026', account.password_hash)
        summary['is_default_password'] = is_default

        return self._json_ok(summary)

    @http.route('/api/v1/loyalty/zalo/phone', type='http',
                auth='public', methods=['POST'], csrf=False, cors='*')
    def resolve_zalo_phone(self, **kwargs):
        """Exchange Zalo Mini App getPhoneNumber token for the real phone.

        Body: {"token": "...", "access_token": "..."}
        Zalo requires app secret_key server-side, never from the Mini App.
        """
        try:
            payload = self._request_json()
            phone_token = (payload.get('token') or payload.get('code') or '').strip()
            access_token = (payload.get('access_token') or '').strip()

            _logger.info(
                'Zalo phone exchange input: has_token=%s token=%s has_access_token=%s access_token=%s',
                bool(phone_token),
                self._mask_secret(phone_token),
                bool(access_token),
                self._mask_secret(access_token),
            )

            if not phone_token or not access_token:
                return self._json_err(
                    'Missing token or access_token',
                    status=400,
                    code='missing_token',
                )

            ICP = request.env['ir.config_parameter'].sudo()
            relay_url = (ICP.get_param('hlv_loyalty.zalo_phone_relay_url') or '').strip()
            relay_key = (ICP.get_param('hlv_loyalty.zalo_phone_relay_key') or '').strip()

            if relay_url:
                if not relay_key:
                    _logger.error('Zalo phone exchange blocked: missing hlv_loyalty.zalo_phone_relay_key')
                    return self._json_err(
                        'Missing Zalo phone relay key configuration on Odoo',
                        status=503,
                        code='missing_zalo_phone_relay_key',
                    )

                headers = {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'x-relay-key': relay_key,
                    'Authorization': 'Bearer %s' % relay_key,
                }
                _logger.info('Zalo phone exchange using relay: url=%s', relay_url)
                zalo_res = requests.post(
                    relay_url,
                    headers=headers,
                    json={
                        'token': phone_token,
                        'access_token': access_token,
                    },
                    timeout=10,
                )
            else:
                secret_key = (
                    ICP.get_param('hlv_loyalty.zalo_secret_key')
                    or ICP.get_param('zalo.secret_key')
                    or ''
                ).strip()
                if not secret_key:
                    _logger.error('Zalo phone exchange blocked: missing hlv_loyalty.zalo_secret_key')
                    return self._json_err(
                        'Missing Zalo secret_key or relay configuration on Odoo',
                        status=503,
                        code='missing_zalo_phone_config',
                    )

                zalo_res = requests.get(
                    'https://graph.zalo.me/v2.0/me/info',
                    headers={
                        'access_token': access_token,
                        'code': phone_token,
                        'secret_key': secret_key,
                    },
                    timeout=10,
                )
            response_text = (zalo_res.text or '')[:2000]
            _logger.info(
                'Zalo phone exchange response: status=%s body=%s',
                zalo_res.status_code,
                response_text,
            )
            zalo_res.raise_for_status()
            zalo_data = zalo_res.json()
        except requests.exceptions.RequestException:
            status_code = getattr(locals().get('zalo_res'), 'status_code', None)
            body = getattr(locals().get('zalo_res'), 'text', '') or ''
            _logger.exception(
                'Zalo phone token exchange request failed: status=%s body=%s',
                status_code,
                body[:2000],
            )
            return self._json_err(
                'Cannot exchange Zalo phone token',
                status=502,
                code='zalo_request_failed',
                zalo_status=status_code,
                zalo_body=body[:1000],
            )
        except ValueError:
            body = getattr(locals().get('zalo_res'), 'text', '') or ''
            _logger.exception('Zalo phone token exchange returned invalid JSON: body=%s', body[:2000])
            return self._json_err(
                'Zalo returned invalid JSON',
                status=502,
                code='zalo_invalid_json',
                zalo_body=body[:1000],
            )
        except Exception:
            _logger.exception('Unexpected error in Zalo phone token exchange')
            return self._json_err(
                'Unexpected Zalo phone exchange error',
                status=500,
                code='unexpected_error',
            )

        if zalo_data.get('error') not in (0, '0', None):
            _logger.warning(
                'Zalo phone token exchange failed: error=%s message=%s data=%s',
                zalo_data.get('error'),
                zalo_data.get('message') or zalo_data.get('error'),
                zalo_data,
            )
            return self._json_err(
                zalo_data.get('message') or 'Zalo rejected phone token',
                status=400,
                code='zalo_rejected_token',
                zalo_error=zalo_data.get('error'),
                zalo_data=zalo_data,
            )

        raw_number = (
            (zalo_data.get('data') or {}).get('number')
            or zalo_data.get('number')
            or ''
        )
        phone = self._normalize_vn_phone(raw_number)
        if not phone:
            _logger.warning('Zalo phone token exchange returned no phone number: %s', zalo_data)
            return self._json_err(
                'Zalo did not return a phone number',
                status=404,
                code='zalo_missing_phone',
                zalo_data=zalo_data,
            )

        return self._json_ok({
            'phone': phone,
            'number': raw_number,
        })

    @http.route('/api/v1/loyalty/partner/<int:partner_id>', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    def get_partner(self, partner_id, **kwargs):
        """GET /api/v1/loyalty/partner/<id>
        Lấy thông tin điểm + hạng + voucher đang có.
        """
        root, portal_phone, error = self._partner_from_portal_phone(partner_id, kwargs.get('phone'))
        if error:
            return error
        summary = self._partner_summary(root)
        summary['phone'] = portal_phone

        # Voucher active
        vouchers = request.env['hlv.loyalty.voucher'].sudo().search([
            ('partner_id', '=', root.id), ('state', '=', 'active'),
        ], order='date_expiry asc')
        summary['active_vouchers'] = [{
            'id': v.id,
            'code': v.code,
            'discount_type': v.discount_type,
            'discount_value': v.discount_value,
            'date_expiry': _vn_datetime(v.date_expiry),
        } for v in vouchers]

        # Lịch sử 10 gần nhất
        family_ids = root._get_loyalty_family_partner_ids()
        history = request.env['hlv.loyalty.history'].sudo().search([
            ('partner_id', 'in', family_ids),
        ], limit=10, order='date desc')
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
        """GET /api/v1/loyalty/partner/<id>/history?limit=20&offset=0

        Optional filters:
        - pt / point_type: all | ranking | exchange
        - st / state: all | pending | confirmed | cancelled
        - tt / transaction_type: all | earn | redeem | return | manual
        - date_from / date_to: YYYY-MM-DD
        """
        root, portal_phone, error = self._partner_from_portal_phone(partner_id, kwargs.get('phone'))
        if error:
            return error

        limit = min(int(kwargs.get('limit', 20)), 100)
        offset = int(kwargs.get('offset', 0))
        family_ids = root._get_loyalty_family_partner_ids()
        active_pt = kwargs.get('pt') or kwargs.get('point_type') or 'all'
        active_st = kwargs.get('st') or kwargs.get('state') or 'all'
        active_tt = kwargs.get('tt') or kwargs.get('transaction_type') or 'all'

        if active_pt not in ('all', 'ranking', 'exchange'):
            active_pt = 'all'
        if active_st not in ('all', 'pending', 'confirmed', 'cancelled'):
            active_st = 'all'
        if active_tt not in ('all', 'earn', 'redeem', 'return', 'manual'):
            active_tt = 'all'

        domain = [('partner_id', 'in', family_ids)]
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
            domain,
            limit=limit, offset=offset, order='date desc',
        )
        total = request.env['hlv.loyalty.history'].sudo().search_count(
            domain
        )
        return self._json_ok({
            'partner_id': root.id,
            'phone': portal_phone,
            'total_points': root.loyalty_total_points,
            'exchange_points': root.loyalty_exchange_points,
            'pending_reward_points': root.loyalty_reward_pending_points,
            'exchange_points_available': root.loyalty_exchange_available_points,
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

    @http.route('/api/v1/loyalty/points/add', type='json',
                auth='public', methods=['POST'], csrf=False, cors='*')
    def add_points(self, **kwargs):
        """POST /api/v1/loyalty/points/add
        Cộng/trừ điểm thủ công.

        Body (JSON):
        {
            "partner_id": 42,
            "points": 100,             // âm để trừ điểm
            "description": "Cộng điểm ưu đãi sinh nhật"
        }
        """
        points = kwargs.get('points')
        description = kwargs.get('description', 'Cộng điểm thủ công (API)')

        if points is None:
            return {'error': 'Thiếu trường points'}
        points = int(points)
        if points == 0:
            return {'error': 'points không được bằng 0'}

        partner_id = kwargs.get('partner_id')
        if not partner_id:
            return {'error': 'Thiếu partner_id'}
        root, error = self._partner_from_portal_phone_rpc(partner_id, kwargs.get('phone'))
        if error:
            return error

        if points < 0 and root.loyalty_total_points + points < 0:
            return {'error': f'Không đủ điểm. Hiện có {root.loyalty_total_points}'}

        request.env['hlv.loyalty.history'].sudo().create({
            'partner_id': root.id,
            'point_amount': points,
            'transaction_type': 'manual',
            'description': description,
            'company_id': request.env.company.id,
        })

        return {
            'success': True,
            'partner_id': root.id,
            'partner_name': root.name,
            'points_added': points,
            'total_points': root.loyalty_total_points,
            'tier': self._tier_dict(root.loyalty_tier_id),
        }

    @http.route('/api/v1/loyalty/vouchers/<int:partner_id>', type='http',
                auth='public', methods=['GET', 'POST', 'OPTIONS'], csrf=False, cors='*')
    def get_partner_vouchers(self, partner_id, **kwargs):
        """GET/POST /api/v1/loyalty/vouchers/<id>?state=active"""
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())
        body = self._request_json()
        phone = kwargs.get('phone') or body.get('phone')
        state = kwargs.get('state') or body.get('state')
        root, portal_phone, error = self._partner_from_portal_phone(partner_id, phone)
        if error:
            return error

        domain = [('partner_id', '=', root.id)]
        if state:
            domain.append(('state', '=', state))

        vouchers = request.env['hlv.loyalty.voucher'].sudo().search(
            domain, order='create_date desc')
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

    @http.route('/api/v1/loyalty/voucher/validate', type='json',
                auth='public', methods=['POST'], csrf=False, cors='*')
    def validate_voucher_external(self, **kwargs):
        """POST /api/v1/loyalty/voucher/validate
        Body: {"code": "VHQ-XXXXX", "partner_id": 42, "order_amount": 500000}
        """
        code = (kwargs.get('code') or '').strip().upper()
        partner_id = kwargs.get('partner_id')
        if not code:
            return {'valid': False, 'error': 'Thiếu mã Voucher'}

        root = None
        if partner_id:
            root, error = self._partner_from_portal_phone_rpc(partner_id, kwargs.get('phone'))
            if error:
                return {'valid': False, 'error': error.get('error'), 'code': error.get('code')}

        voucher = request.env['hlv.loyalty.voucher'].sudo().search(
            [('code', '=', code)], limit=1)
        if not voucher:
            return {'valid': False, 'error': 'Mã Voucher không tồn tại'}
        if voucher.state != 'active':
            return {'valid': False, 'error': f'Voucher trạng thái: {voucher.state}'}
        if voucher.date_expiry and voucher.date_expiry < odoo_fields.Datetime.now():
            return {'valid': False, 'error': 'Voucher đã hết hạn'}

        if root and voucher.partner_id.id not in root._get_loyalty_family_partner_ids():
            return {'valid': False, 'error': 'Voucher không thuộc sở hữu của khách hàng này'}

        order_amount = float(kwargs.get('order_amount', 0))
        if voucher.min_order_amount > 0 and order_amount < voucher.min_order_amount:
            return {'valid': False,
                    'error': f'Cần đơn tối thiểu {voucher.min_order_amount:,.0f} VNĐ'}

        discount = voucher.compute_discount_amount(order_amount) if order_amount > 0 else 0
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

    @http.route('/api/v1/loyalty/program/config', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    def get_program_config(self, **kwargs):
        """GET /api/v1/loyalty/program/config
        Trả về cấu hình chương trình: tỷ lệ quy đổi, mô tả điểm.
        """
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
        """GET/POST /api/v1/loyalty/redeem/packages
        Danh sách gói quà có thể đổi (active).
        """
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
            'gift_product_name': p.gift_product_id.name if p.gift_product_id else '',
            'gift_qty': p.gift_qty,
        } for p in packages])

    @staticmethod
    def _reward_request_dict(req):
        return {
            'id': req.id,
            'name': req.name,
            'request_type': req.request_type,
            'points_required': req.points_required,
            'cash_value': req.cash_value,
            'voucher_id': req.voucher_id.id if req.voucher_id else None,
            'voucher_code': req.voucher_id.code if req.voucher_id else '',
            'package_name': req.package_id.name if req.package_id else '',
            'state': req.state,
            'date_request': _vn_datetime(req.date_request),
            'customer_note': req.customer_note or '',
        }

    @http.route('/api/v1/loyalty/redeem/requests', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    def list_redeem_requests(self, **kwargs):
        """GET /api/v1/loyalty/redeem/requests?partner_id=42&state=all"""
        partner_id = kwargs.get('partner_id')
        if not partner_id:
            return self._json_err('Thiếu partner_id', status=400, code='MISSING_PARTNER_ID')

        root, portal_phone, error = self._partner_from_portal_phone(partner_id, kwargs.get('phone'))
        if error:
            return error
        domain = [('partner_id', 'in', root._get_loyalty_family_partner_ids())]
        state = kwargs.get('state') or 'all'
        if state in ('pending', 'done', 'cancelled'):
            domain.append(('state', '=', state))

        requests = request.env['hlv.loyalty.reward.request'].sudo().search(
            domain, order='date_request desc, id desc'
        )
        return self._json_ok({
            'success': True,
            'data': {
                'requests': [self._reward_request_dict(req) for req in requests],
                'exchange_points': root.loyalty_exchange_points,
                'pending_reward_points': root.loyalty_reward_pending_points,
                'exchange_points_available': root.loyalty_exchange_available_points,
                'phone': portal_phone,
            },
        })

    @http.route('/api/v1/loyalty/redeem/submit', type='json',
                auth='public', methods=['POST'], csrf=False, cors='*')
    def submit_redeem(self, **kwargs):
        """POST /api/v1/loyalty/redeem/submit
        Tạo yêu cầu đổi thưởng (quà hoặc tiền mặt).

        Body — đổi quà:
        {
            "partner_id": 42,
            "request_type": "gift",
            "package_id": 3
        }

        Body — đổi tiền mặt:
        {
            "partner_id": 42,
            "request_type": "cash",
            "points_to_redeem": 500,
            "bank_name": "Vietcombank",
            "account_number": "1234567890",
            "account_name": "NGUYEN VAN A",
            "customer_note": "..."
        }
        """
        partner_id = kwargs.get('partner_id')
        request_type = kwargs.get('request_type', 'gift')

        if not partner_id:
            return {'error': 'Thiếu partner_id'}
        if request_type not in ('gift', 'cash'):
            return {'error': 'request_type phải là gift hoặc cash'}

        root, error = self._partner_from_portal_phone_rpc(partner_id, kwargs.get('phone'))
        if error:
            return error
        balance_exchange = root.loyalty_exchange_points
        avail_exchange = root.loyalty_exchange_available_points
        pending_reward_points = root.loyalty_reward_pending_points
        insufficient_code = 'PENDING_REWARD_POINTS' if pending_reward_points else 'INSUFFICIENT_POINTS'

        vals = {
            'partner_id': root.id,
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
            'exchange_points': root.loyalty_exchange_points,
            'pending_reward_points': root.loyalty_reward_pending_points,
            'exchange_points_available': root.loyalty_exchange_available_points,
            'exchange_points_remaining': max(avail_exchange - req.points_required, 0),
            'message': message,
        }

    @http.route([
        '/api/v1/loyalty/redeem/cancel',
        '/api/v1/loyalty/redeem/requests/<int:request_id>/cancel',
    ], type='json', auth='public', methods=['POST'], csrf=False, cors='*')
    def cancel_redeem_request(self, request_id=None, **kwargs):
        """POST /api/v1/loyalty/redeem/cancel
        Body: {"partner_id": 42, "request_id": 123}
        """
        partner_id = kwargs.get('partner_id')
        request_id = request_id or kwargs.get('request_id')
        if not partner_id:
            return {'error': 'Thiếu partner_id'}
        if not request_id:
            return {'error': 'Thiếu request_id'}

        root, error = self._partner_from_portal_phone_rpc(partner_id, kwargs.get('phone'))
        if error:
            return error

        req = request.env['hlv.loyalty.reward.request'].sudo().browse(int(request_id))
        if not req.exists() or req.partner_id.id not in root._get_loyalty_family_partner_ids():
            return {'error': 'Yêu cầu đổi thưởng không tồn tại', 'code': 'REQUEST_NOT_FOUND'}
        if req.state != 'pending':
            return {
                'error': 'Chỉ hủy được yêu cầu đang chờ xử lý',
                'code': 'REQUEST_NOT_PENDING',
                'state': req.state,
            }

        try:
            req.action_cancel()
        except UserError as exc:
            return {'error': str(exc), 'code': 'CANCEL_FAILED'}

        return {
            'success': True,
            'request_id': req.id,
            'request_name': req.name,
            'state': req.state,
            'exchange_points': root.loyalty_exchange_points,
            'pending_reward_points': root.loyalty_reward_pending_points,
            'exchange_points_available': root.loyalty_exchange_available_points,
            'message': 'Yêu cầu đổi thưởng đã được hủy.',
        }

    # ── Account management (đổi mật khẩu / đổi SĐT) ─────────────────────────

    def _account_from_portal_phone_rpc(self, partner_id, phone):
        """Xác thực partner_id + phone → trả về account (hoặc error dict)."""
        try:
            partner = request.env['res.partner'].sudo().browse(int(partner_id))
        except Exception:
            return None, {'error': 'Invalid partner_id', 'code': 'INVALID_PARTNER_ID'}
        if not partner.exists():
            return None, {'error': 'Khach hang khong ton tai', 'code': 'PARTNER_NOT_FOUND'}

        normalized = self._normalize_vn_phone(phone)
        if not normalized:
            return None, {'error': 'Missing phone', 'code': 'MISSING_PHONE'}

        root = partner._get_loyalty_root()
        accounts = request.env['hlv.loyalty.portal.account'].sudo().search([
            ('portal_phone', '=', normalized),
            ('active', '=', True),
        ])
        account = accounts.filtered(lambda acc: acc.partner_id._get_loyalty_root().id == root.id)[:1]
        if not account:
            return None, {'error': 'Missing or invalid partner_id/phone', 'code': 'UNAUTHORIZED'}
        return account, None

    @http.route('/api/v1/loyalty/account/change-password', type='json',
                auth='public', methods=['POST'], csrf=False, cors='*')
    def change_password(self, **kwargs):
        """POST /api/v1/loyalty/account/change-password
        Body: {"partner_id": 42, "phone": "0901234567",
               "old_password": "...", "new_password": "...", "confirm_password": "..."}
        """
        partner_id = kwargs.get('partner_id')
        if not partner_id:
            return {'error': 'Thiếu partner_id', 'code': 'MISSING_PARTNER_ID'}

        account, error = self._account_from_portal_phone_rpc(partner_id, kwargs.get('phone'))
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
        """POST /api/v1/loyalty/account/change-phone
        Body: {"partner_id": 42, "phone": "0901234567", "new_phone": "0909999999"}
        """
        partner_id = kwargs.get('partner_id')
        if not partner_id:
            return {'error': 'Thiếu partner_id', 'code': 'MISSING_PARTNER_ID'}

        account, error = self._account_from_portal_phone_rpc(partner_id, kwargs.get('phone'))
        if error:
            return error

        new_phone = (kwargs.get('new_phone') or '').strip()
        if not new_phone:
            return {'error': 'Số điện thoại mới không được để trống', 'code': 'MISSING_NEW_PHONE'}
        if not re.match(r'^[\d\s\-\+]{7,15}$', new_phone):
            return {'error': 'Số điện thoại không hợp lệ', 'code': 'INVALID_PHONE'}

        normalized = self._normalize_vn_phone(new_phone)
        duplicate = request.env['hlv.loyalty.portal.account'].sudo().search([
            ('portal_phone', '=', normalized),
            ('active', '=', True),
            ('id', '!=', account.id),
        ], limit=1)
        if duplicate:
            return {'error': 'Số điện thoại đã được sử dụng bởi tài khoản khác', 'code': 'PHONE_EXISTS'}

        account.sudo().write({'portal_phone': new_phone})

        return {'success': True, 'message': 'Đổi số điện thoại thành công.', 'new_phone': normalized}
