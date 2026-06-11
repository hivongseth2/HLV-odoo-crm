# -*- coding: utf-8 -*-
import base64
import json
import logging
import requests
from datetime import timedelta
from odoo import fields as odoo_fields, http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class LoyaltyAPIController(http.Controller):
    """API Controller cho tích hợp App Mobile / Website bên ngoài."""

    @http.route('/api/loyalty/points/<int:partner_id>', type='http',
                auth='user', methods=['GET'], csrf=False)
    def get_partner_points(self, partner_id, **kwargs):
        """Lấy số điểm hiện tại của khách hàng.

        GET /api/loyalty/points/<partner_id>
        """
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return Response(
                json.dumps({'error': 'Khách hàng không tồn tại'}),
                status=404, content_type='application/json',
            )
        return Response(
            json.dumps({
                'partner_id': partner.id,
                'partner_name': partner.name,
                'total_points': partner.loyalty_total_points,
            }),
            status=200, content_type='application/json',
        )

    @http.route('/api/loyalty/history/<int:partner_id>', type='http',
                auth='user', methods=['GET'], csrf=False)
    def get_partner_history(self, partner_id, **kwargs):
        """Lấy lịch sử điểm của khách hàng.

        GET /api/loyalty/history/<partner_id>?limit=20&offset=0
        """
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return Response(
                json.dumps({'error': 'Khách hàng không tồn tại'}),
                status=404, content_type='application/json',
            )

        limit = min(int(kwargs.get('limit', 20)), 100)
        offset = int(kwargs.get('offset', 0))

        history_records = request.env['hlv.loyalty.history'].sudo().search(
            [('partner_id', '=', partner_id)],
            limit=limit, offset=offset, order='date desc',
        )
        data = []
        for rec in history_records:
            data.append({
                'id': rec.id,
                'date': rec.date.isoformat() if rec.date else None,
                'point_amount': rec.point_amount,
                'transaction_type': rec.transaction_type,
                'description': rec.description or '',
                'company': rec.company_id.name or '',
            })
        return Response(
            json.dumps({
                'partner_id': partner_id,
                'total_points': partner.loyalty_total_points,
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
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return Response(
                json.dumps({'error': 'Khách hàng không tồn tại'}),
                status=404, content_type='application/json',
            )

        domain = [('partner_id', '=', partner_id)]
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
                'date_issued': v.date_issued.isoformat() if v.date_issued else None,
                'date_expiry': v.date_expiry.isoformat() if v.date_expiry else None,
                'package_name': v.package_id.name or '',
            })
        return Response(
            json.dumps({
                'partner_id': partner_id,
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

        partner = request.env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {'error': 'Khách hàng không tồn tại'}

        package = request.env['hlv.loyalty.voucher.package'].sudo().browse(int(package_id))
        if not package.exists() or not package.active:
            return {'error': 'Gói Voucher không tồn tại hoặc đã ngừng'}

        if partner.loyalty_total_points < package.points_required:
            return {
                'error': f'Không đủ điểm. Cần {package.points_required}, có {partner.loyalty_total_points}',
            }

        # Tạo wizard context và thực hiện đổi 123
        validity_days = package._get_validity_days()
        date_expiry = odoo_fields.Datetime.now() + timedelta(days=validity_days)

        voucher = request.env['hlv.loyalty.voucher'].sudo().create({
            'partner_id': partner.id,
            'package_id': package.id,
            'date_expiry': date_expiry,
        })

        request.env['hlv.loyalty.history'].sudo().create({
            'partner_id': partner.id,
            'point_amount': -package.points_required,
            'transaction_type': 'redeem',
            'description': f'Đổi Voucher [{package.name}] - Mã: {voucher.code} (API)',
            'voucher_id': voucher.id,
            'company_id': request.env.company.id,
        })

        return {
            'success': True,
            'voucher': {
                'code': voucher.code,
                'discount_type': voucher.discount_type,
                'discount_value': voucher.discount_value,
                'date_expiry': date_expiry.isoformat(),
            },
            'remaining_points': partner.loyalty_total_points,
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

        voucher = request.env['hlv.loyalty.voucher'].sudo().search([
            ('code', '=', code),
        ], limit=1)

        if not voucher:
            return {'valid': False, 'error': 'Mã Voucher không tồn tại'}

        if voucher.state != 'active':
            return {'valid': False, 'error': f'Voucher đang ở trạng thái: {voucher.state}'}

        if voucher.date_expiry and voucher.date_expiry < odoo_fields.Datetime.now():
            return {'valid': False, 'error': 'Voucher đã hết hạn'}

        if partner_id and voucher.partner_id.id != int(partner_id):
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
                'date_expiry': voucher.date_expiry.isoformat() if voucher.date_expiry else None,
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
    def _json_ok(data, status=200):
        return Response(json.dumps(data, default=str),
                        status=status, content_type='application/json')

    @staticmethod
    def _json_err(msg, status=400, **extra):
        body = {'error': msg}
        body.update(extra)
        return Response(json.dumps(body, default=str),
                        status=status, content_type='application/json')

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
        # tiers sorted asc — next tier là tier đầu tiên có min_points > pts
        next_tier = next((t for t in tiers if t.min_points > pts), None)
        return {
            'id': partner.id,
            'name': partner.name,
            'phone': partner.phone or '',
            'email': partner.email or '',
            'ranking_points': pts,
            'exchange_points': exc_pts,
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
                auth='public', methods=['GET'], csrf=False, cors='*')
    def list_tiers(self, **kwargs):
        """GET /api/v1/loyalty/tiers
        Trả về danh sách hạng thành viên kèm ảnh và quyền lợi.
        """
        tiers = request.env['hlv.loyalty.tier'].sudo().search([], order='min_points asc')
        return self._json_ok([self._tier_dict(t) for t in tiers])

    @http.route('/api/v1/loyalty/partner/lookup', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    def lookup_partner(self, **kwargs):
        """GET /api/v1/loyalty/partner/lookup?phone=0901234567
           GET /api/v1/loyalty/partner/lookup?email=abc@example.com

        Tìm khách hàng theo SĐT hoặc email, trả về điểm + hạng.
        """
        phone = (kwargs.get('phone') or '').strip()
        email = (kwargs.get('email') or '').strip().lower()

        if not phone and not email:
            return self._json_err('Cần truyền phone hoặc email')

        partner_ids = set()

        if phone:
            # Chỉ tìm qua portal_phone (đã chuẩn hóa)
            accounts = request.env['hlv.loyalty.portal.account'].sudo().search(
                [('portal_phone', 'like', phone), ('active', '=', True)], limit=5
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
                results.append(self._partner_summary(root))

        if not results:
            return self._json_err('Không tìm thấy khách hàng', status=404)
        return self._json_ok(results if len(results) > 1 else results[0])

    @http.route('/api/v1/loyalty/zalo/phone', type='http',
                auth='public', methods=['POST'], csrf=False, cors='*')
    def resolve_zalo_phone(self, **kwargs):
        """Exchange Zalo Mini App getPhoneNumber token for the real phone.

        Body: {"token": "...", "access_token": "..."}
        Zalo requires app secret_key server-side, never from the Mini App.
        """
        payload = self._request_json()
        phone_token = (payload.get('token') or payload.get('code') or '').strip()
        access_token = (payload.get('access_token') or '').strip()

        if not phone_token or not access_token:
            return self._json_err('Thiếu token hoặc access_token', status=400)

        ICP = request.env['ir.config_parameter'].sudo()
        secret_key = (
            ICP.get_param('hlv_loyalty.zalo_secret_key')
            or ICP.get_param('zalo.secret_key')
            or ''
        ).strip()
        if not secret_key:
            return self._json_err('Chưa cấu hình Zalo secret_key trên Odoo', status=500)

        try:
            zalo_res = requests.get(
                'https://graph.zalo.me/v2.0/me/info',
                headers={
                    'access_token': access_token,
                    'code': phone_token,
                    'secret_key': secret_key,
                },
                timeout=10,
            )
            zalo_res.raise_for_status()
            zalo_data = zalo_res.json()
        except requests.exceptions.RequestException:
            _logger.exception('Zalo phone token exchange request failed')
            return self._json_err('Không thể kết nối Zalo để lấy số điện thoại', status=502)
        except ValueError:
            _logger.exception('Zalo phone token exchange returned invalid JSON')
            return self._json_err('Zalo trả về dữ liệu không hợp lệ', status=502)

        if zalo_data.get('error') not in (0, '0', None):
            _logger.warning(
                'Zalo phone token exchange failed: %s',
                zalo_data.get('message') or zalo_data.get('error'),
            )
            return self._json_err(
                zalo_data.get('message') or 'Zalo từ chối token số điện thoại',
                status=400,
            )

        raw_number = (
            (zalo_data.get('data') or {}).get('number')
            or zalo_data.get('number')
            or ''
        )
        phone = self._normalize_vn_phone(raw_number)
        if not phone:
            return self._json_err('Zalo không trả về số điện thoại', status=404)

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
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return self._json_err('Khách hàng không tồn tại', status=404)

        root = partner._get_loyalty_root()
        summary = self._partner_summary(root)

        # Voucher active
        vouchers = request.env['hlv.loyalty.voucher'].sudo().search([
            ('partner_id', '=', root.id), ('state', '=', 'active'),
        ], order='date_expiry asc')
        summary['active_vouchers'] = [{
            'id': v.id,
            'code': v.code,
            'discount_type': v.discount_type,
            'discount_value': v.discount_value,
            'date_expiry': v.date_expiry.isoformat() if v.date_expiry else None,
        } for v in vouchers]

        # Lịch sử 10 gần nhất
        history = request.env['hlv.loyalty.history'].sudo().search([
            ('partner_id', '=', root.id),
        ], limit=10, order='date desc')
        summary['recent_history'] = [{
            'id': h.id,
            'date': h.date.isoformat() if h.date else None,
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
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return self._json_err('Khách hàng không tồn tại', status=404)

        limit = min(int(kwargs.get('limit', 20)), 100)
        offset = int(kwargs.get('offset', 0))
        root = partner._get_loyalty_root()
        history = request.env['hlv.loyalty.history'].sudo().search(
            [('partner_id', '=', root.id)],
            limit=limit, offset=offset, order='date desc',
        )
        total = request.env['hlv.loyalty.history'].sudo().search_count(
            [('partner_id', '=', root.id)]
        )
        return self._json_ok({
            'partner_id': partner_id,
            'total_points': root.loyalty_total_points,
            'total_records': total,
            'limit': limit,
            'offset': offset,
            'records': [{
                'id': h.id,
                'date': h.date.isoformat() if h.date else None,
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
            "partner_id": 42,          // hoặc dùng phone/email
            "phone": "0901234567",
            "email": "abc@example.com",
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

        # Tìm partner
        partner = None
        if kwargs.get('partner_id'):
            partner = request.env['res.partner'].sudo().browse(int(kwargs['partner_id']))
            if not partner.exists():
                return {'error': 'Khách hàng không tồn tại'}
        elif kwargs.get('phone'):
            partner = request.env['res.partner'].sudo().search(
                [('phone', 'like', kwargs['phone'].strip())], limit=1)
        elif kwargs.get('email'):
            partner = request.env['res.partner'].sudo().search(
                [('email', '=ilike', kwargs['email'].strip())], limit=1)

        if not partner:
            return {'error': 'Không tìm thấy khách hàng'}

        root = partner._get_loyalty_root()

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
                auth='public', methods=['GET'], csrf=False, cors='*')
    def get_partner_vouchers(self, partner_id, **kwargs):
        """GET /api/v1/loyalty/vouchers/<id>?state=active"""
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return self._json_err('Khách hàng không tồn tại', status=404)

        root_id = partner._get_loyalty_root().id
        domain = [('partner_id', '=', root_id)]
        if kwargs.get('state'):
            domain.append(('state', '=', kwargs['state']))

        vouchers = request.env['hlv.loyalty.voucher'].sudo().search(
            domain, order='create_date desc')
        return self._json_ok([{
            'id': v.id,
            'code': v.code,
            'state': v.state,
            'discount_type': v.discount_type,
            'discount_value': v.discount_value,
            'max_discount_amount': v.max_discount_amount,
            'date_issued': v.date_issued.isoformat() if v.date_issued else None,
            'date_expiry': v.date_expiry.isoformat() if v.date_expiry else None,
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
        if not code:
            return {'valid': False, 'error': 'Thiếu mã Voucher'}

        voucher = request.env['hlv.loyalty.voucher'].sudo().search(
            [('code', '=', code)], limit=1)
        if not voucher:
            return {'valid': False, 'error': 'Mã Voucher không tồn tại'}
        if voucher.state != 'active':
            return {'valid': False, 'error': f'Voucher trạng thái: {voucher.state}'}
        if voucher.date_expiry and voucher.date_expiry < odoo_fields.Datetime.now():
            return {'valid': False, 'error': 'Voucher đã hết hạn'}

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
                'date_expiry': voucher.date_expiry.isoformat() if voucher.date_expiry else None,
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
                auth='public', methods=['GET'], csrf=False, cors='*')
    def list_redeem_packages(self, **kwargs):
        """GET /api/v1/loyalty/redeem/packages
        Danh sách gói quà có thể đổi (active).
        """
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

        partner = request.env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {'error': 'Khách hàng không tồn tại'}

        root = partner._get_loyalty_root()
        avail_exchange = root.loyalty_exchange_points

        vals = {
            'partner_id': root.id,
            'request_type': request_type,
            'balance_at_request': avail_exchange,
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
                    'error': f'Không đủ điểm đổi thưởng. '
                             f'Cần {package.points_required:,} điểm, bạn có {avail_exchange:,} điểm.'
                }
            vals['package_id'] = package.id

        elif request_type == 'cash':
            points_to_redeem = int(kwargs.get('points_to_redeem') or 0)
            if points_to_redeem <= 0:
                return {'error': 'points_to_redeem phải lớn hơn 0'}
            if avail_exchange < points_to_redeem:
                return {
                    'error': f'Không đủ điểm đổi thưởng. '
                             f'Cần {points_to_redeem:,} điểm, bạn có {avail_exchange:,} điểm.'
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

        req = request.env['hlv.loyalty.reward.request'].sudo().create(vals)

        return {
            'success': True,
            'request_id': req.id,
            'request_name': req.name,
            'request_type': req.request_type,
            'points_required': req.points_required,
            'cash_value': req.cash_value,
            'exchange_points_remaining': avail_exchange - req.points_required,
            'message': 'Yêu cầu đổi thưởng đã được gửi thành công. Vui lòng chờ xét duyệt.',
        }

