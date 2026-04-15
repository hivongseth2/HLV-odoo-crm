# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class LoyaltyPublicPortal(http.Controller):

    @http.route('/loyalty', type='http', auth='public', website=True, sitemap=False)
    def loyalty_home(self, **kwargs):
        """Trang chủ tra cứu loyalty."""
        tiers = request.env['hlv.loyalty.tier'].sudo().search(
            [('active', '=', True)], order='min_points asc'
        )
        return request.render('hlv_loyalty.loyalty_public_home', {
            'tiers': tiers,
            'error': None,
            'partner': None,
        })

    @http.route('/loyalty/search', type='http', auth='public', website=True,
                sitemap=False, methods=['GET', 'POST'])
    def loyalty_search(self, **post):
        """Tra cứu điểm và hạng bằng SĐT hoặc email."""
        tiers = request.env['hlv.loyalty.tier'].sudo().search(
            [('active', '=', True)], order='min_points asc'
        )

        keyword = (post.get('keyword') or '').strip()
        if not keyword:
            return request.render('hlv_loyalty.loyalty_public_home', {
                'tiers': tiers,
                'error': 'Vui lòng nhập số điện thoại hoặc email.',
                'partner': None,
                'keyword': keyword,
            })

        # Tìm partner theo SĐT, email hoặc tên — loại bỏ delivery address
        _EXCLUDE_TYPES = ['delivery', 'invoice', 'other', 'private']
        partner = request.env['res.partner'].sudo().search([
            '|', '|',
            ('phone', 'ilike', keyword),
            ('email', 'ilike', keyword),
            ('name', 'ilike', keyword),
            ('type', 'not in', _EXCLUDE_TYPES),
            ('loyalty_total_points', '>', 0),
        ], order='loyalty_total_points desc', limit=1)

        if not partner:
            # Fallback: bỏ điều kiện điểm
            partner = request.env['res.partner'].sudo().search([
                '|', '|',
                ('phone', 'ilike', keyword),
                ('email', 'ilike', keyword),
                ('name', 'ilike', keyword),
                ('type', 'not in', _EXCLUDE_TYPES),
            ], limit=1)

        if not partner:
            return request.render('hlv_loyalty.loyalty_public_home', {
                'tiers': tiers,
                'error': f'Không tìm thấy khách hàng với thông tin: "{keyword}"',
                'partner': None,
                'keyword': keyword,
            })

        # Dùng commercial_partner_id để lấy điểm
        root_partner = partner.commercial_partner_id or partner

        # Lấy voucher đang active
        active_vouchers = request.env['hlv.loyalty.voucher'].sudo().search([
            ('partner_id', '=', root_partner.id),
            ('state', '=', 'active'),
        ])

        # Lấy lịch sử gần nhất
        recent_history = request.env['hlv.loyalty.history'].sudo().search([
            ('partner_id', '=', root_partner.id),
        ], order='date desc', limit=10)

        # Tier tiếp theo
        next_tier = None
        if root_partner.loyalty_tier_id:
            next_tier = request.env['hlv.loyalty.tier'].sudo().search([
                ('min_points', '>', root_partner.loyalty_total_points),
                ('active', '=', True),
            ], order='min_points asc', limit=1)

        return request.render('hlv_loyalty.loyalty_public_result', {
            'tiers': tiers,
            'partner': root_partner,
            'active_vouchers': active_vouchers,
            'recent_history': recent_history,
            'next_tier': next_tier,
            'keyword': keyword,
        })
