# -*- coding: utf-8 -*-
import json
import logging
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

        # Tạo wizard context và thực hiện đổi
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
    def _json_err(msg, status=400):
        return Response(json.dumps({'error': msg}),
                        status=status, content_type='application/json')

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
    def _partner_summary(partner):
        tiers = request.env['hlv.loyalty.tier'].sudo().search([], order='min_points asc')
        tier = partner.loyalty_tier_id
        pts = partner.loyalty_total_points
        # tiers sorted asc — next tier là tier đầu tiên có min_points > pts
        next_tier = next((t for t in tiers if t.min_points > pts), None)
        return {
            'id': partner.id,
            'name': partner.name,
            'phone': partner.phone or '',
            'email': partner.email or '',
            'total_points': pts,
            'tier': LoyaltyExternalAPI._tier_dict(tier),
            'next_tier': LoyaltyExternalAPI._tier_dict(next_tier),
            'points_to_next': (next_tier.min_points - pts) if next_tier else 0,
        }

    # ── Endpoints ────────────────────────────────────────────────────────────

    @http.route('/api/v1/loyalty/tiers', type='http',
                auth='api_key', methods=['GET'], csrf=False)
    def list_tiers(self, **kwargs):
        """GET /api/v1/loyalty/tiers
        Trả về danh sách hạng thành viên kèm ảnh và quyền lợi.
        """
        tiers = request.env['hlv.loyalty.tier'].sudo().search([], order='min_points asc')
        return self._json_ok([self._tier_dict(t) for t in tiers])

    @http.route('/api/v1/loyalty/partner/lookup', type='http',
                auth='api_key', methods=['GET'], csrf=False)
    def lookup_partner(self, **kwargs):
        """GET /api/v1/loyalty/partner/lookup?phone=0901234567
           GET /api/v1/loyalty/partner/lookup?email=abc@example.com

        Tìm khách hàng theo SĐT hoặc email, trả về điểm + hạng.
        """
        phone = (kwargs.get('phone') or '').strip()
        email = (kwargs.get('email') or '').strip().lower()

        if not phone and not email:
            return self._json_err('Cần truyền phone hoặc email')

        domain = [('customer_rank', '>', 0)]
        if phone:
            domain.append(('phone', 'like', phone))
        elif email:
            domain.append(('email', '=ilike', email))

        partners = request.env['res.partner'].sudo().search(domain, limit=5)
        # Ưu tiên commercial_partner_id (root)
        results = []
        seen = set()
        for p in partners:
            root = p.commercial_partner_id or p
            if root.id not in seen:
                seen.add(root.id)
                results.append(self._partner_summary(root))

        if not results:
            return self._json_err('Không tìm thấy khách hàng', status=404)
        return self._json_ok(results if len(results) > 1 else results[0])

    @http.route('/api/v1/loyalty/partner/<int:partner_id>', type='http',
                auth='api_key', methods=['GET'], csrf=False)
    def get_partner(self, partner_id, **kwargs):
        """GET /api/v1/loyalty/partner/<id>
        Lấy thông tin điểm + hạng + voucher đang có.
        """
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return self._json_err('Khách hàng không tồn tại', status=404)

        root = partner.commercial_partner_id or partner
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
            'transaction_type': h.transaction_type,
            'description': h.description or '',
        } for h in history]

        return self._json_ok(summary)

    @http.route('/api/v1/loyalty/partner/<int:partner_id>/history', type='http',
                auth='api_key', methods=['GET'], csrf=False)
    def get_partner_history(self, partner_id, **kwargs):
        """GET /api/v1/loyalty/partner/<id>/history?limit=20&offset=0"""
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return self._json_err('Khách hàng không tồn tại', status=404)

        limit = min(int(kwargs.get('limit', 20)), 100)
        offset = int(kwargs.get('offset', 0))
        history = request.env['hlv.loyalty.history'].sudo().search(
            [('partner_id', '=', partner.commercial_partner_id.id or partner_id)],
            limit=limit, offset=offset, order='date desc',
        )
        total = request.env['hlv.loyalty.history'].sudo().search_count(
            [('partner_id', '=', partner.commercial_partner_id.id or partner_id)]
        )
        return self._json_ok({
            'partner_id': partner_id,
            'total_points': (partner.commercial_partner_id or partner).loyalty_total_points,
            'total_records': total,
            'limit': limit,
            'offset': offset,
            'records': [{
                'id': h.id,
                'date': h.date.isoformat() if h.date else None,
                'point_amount': h.point_amount,
                'transaction_type': h.transaction_type,
                'description': h.description or '',
            } for h in history],
        })

    @http.route('/api/v1/loyalty/points/add', type='json',
                auth='api_key', methods=['POST'], csrf=False)
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

        root = partner.commercial_partner_id or partner

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
                auth='api_key', methods=['GET'], csrf=False)
    def get_partner_vouchers(self, partner_id, **kwargs):
        """GET /api/v1/loyalty/vouchers/<id>?state=active"""
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return self._json_err('Khách hàng không tồn tại', status=404)

        root_id = (partner.commercial_partner_id or partner).id
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
        } for v in vouchers])

    @http.route('/api/v1/loyalty/voucher/validate', type='json',
                auth='api_key', methods=['POST'], csrf=False)
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

