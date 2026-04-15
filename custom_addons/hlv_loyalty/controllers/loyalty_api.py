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
