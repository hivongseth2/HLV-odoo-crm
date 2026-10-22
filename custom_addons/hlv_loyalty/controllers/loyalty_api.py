# -*- coding: utf-8 -*-
import base64
import json
import logging
import requests
from datetime import timedelta, timezone
from odoo import fields as odoo_fields, http
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
        if not package.exists():
            return {'error': 'Gói Voucher không tồn tại hoặc đã ngừng'}
        reason = package._get_unavailable_reason()
        if reason:
            return {'error': reason}

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
        return {
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
            'Access-Control-Max-Age': '86400',
        }

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

    # Tài khoản mới dùng chung một mật khẩu mặc định, nên đăng nhập là chỗ dò
    # mật khẩu theo từng SĐT. Giới hạn theo IP.
    LOGIN_RATE_LIMIT = 10
    LOGIN_RATE_WINDOW = 600

    def _login_rate_limited(self):
        """Trả response 429 nếu IP đăng nhập quá giới hạn, ngược lại None.

        remote_addr là IP thật khi Odoo chạy proxy_mode (Odoo.sh); không đọc
        X-Forwarded-For trực tiếp vì client tự đặt được header đó.
        """
        ip = request.httprequest.remote_addr or 'unknown'
        allowed = request.env['hlv.loyalty.rate.limit.hit'].sudo().consume(
            f'loyalty_login:{ip}', self.LOGIN_RATE_LIMIT, self.LOGIN_RATE_WINDOW)
        if allowed:
            return None
        return self._json_err('Đăng nhập sai quá nhiều lần, vui lòng thử lại sau ít phút',
                              status=429, code='RATE_LIMITED')

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


    @http.route('/api/v1/loyalty/auth/login', type='http',
                auth='public', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def auth_login(self, **kwargs):
        """POST /api/v1/loyalty/auth/login
        Body JSON: {"phone": "0901234567", "password": "..."} or {"login": "...", "password": "..."}

        Xác thực tài khoản Portal (hlv.loyalty.portal.account) bằng SĐT/Username + Mật khẩu.
        """
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
            if PortalAccount.find_disabled_account(phone_normalized, [login_input]):
                return self._json_err('Tài khoản của bạn đã bị vô hiệu hóa. Vui lòng liên hệ cửa hàng để được hỗ trợ.',
                                      status=403, code='ACCOUNT_DISABLED')
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
                'reward_type': voucher.reward_type,
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
            'gift_product_name': p.gift_product_id.name if p.gift_product_id else '',
            'gift_qty': p.gift_qty,
        } for p in packages])


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


