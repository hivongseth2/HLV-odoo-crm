# -*- coding: utf-8 -*-
"""
Loyalty Proxy API – Endpoints ủy quyền (proxy) cho module `hlv_loyalty`.

Giải quyết vấn đề: Zalo Mini App WebView trên iOS/Android không gọi được
trực tiếp tới endpoint của `hlv_loyalty` (controller khác class, CORS/response
format khác nhau). Các endpoint ở đây:
  • Kế thừa ZaloBaseAPI → dùng chung CORS headers, response format chuẩn
    `{success: true, data: ...}`.
  • Chỉ đọc dữ liệu ORM (`sudo().search`), KHÔNG duplicate business logic.
"""

import logging

from odoo import http
from odoo.http import request

from .base_api import ZaloBaseAPI

_logger = logging.getLogger(__name__)


class ZaloLoyaltyProxyAPI(ZaloBaseAPI, http.Controller):
    """Proxy các endpoint loyalty cho Zalo Mini App."""

    # ── Gói đổi quà (Redeem Packages) ───────────────────────────────────

    @http.route(
        [
            '/api/v1/zalo/loyalty/redeem-packages',
            '/api/v1/zalo/loyalty/voucher-packages',
            '/api/v1/zalo/loyalty/packages',
        ],
        type='http', auth='public',
        methods=['GET', 'POST', 'OPTIONS'], csrf=False,
    )
    def zalo_redeem_packages(self, **kwargs):
        """GET/POST /api/v1/zalo/loyalty/redeem-packages
        Proxy trả về danh sách gói quà đổi điểm (active) từ hlv.loyalty.voucher.package.
        Response format: {success: true, data: [{...}, ...]}
        """
        opt = self._check_options()
        if opt:
            return opt

        try:
            packages = request.env['hlv.loyalty.voucher.package'].sudo().search(
                [('active', '=', True)], order='points_required asc'
            )
            data = [{
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
            } for p in packages]
            return self._response_success_cached(data, max_age=300)
        except Exception as e:
            _logger.exception("zalo_redeem_packages error: %s", e)
            return self._response_error("LOYALTY_ERROR", str(e), status=500)

    # ── Voucher cá nhân (User Vouchers) ─────────────────────────────────

    @http.route(
        [
            '/api/v1/zalo/loyalty/vouchers/<int:partner_id>',
            '/api/v1/zalo/loyalty/my-vouchers/<int:partner_id>',
        ],
        type='http', auth='public',
        methods=['GET', 'POST', 'OPTIONS'], csrf=False,
    )
    def zalo_user_vouchers(self, partner_id, **kwargs):
        """GET /api/v1/zalo/loyalty/vouchers/<partner_id>?state=active
        Proxy trả về danh sách voucher cá nhân đã phát hành cho partner.
        Response format: {success: true, data: [{...}, ...]}
        """
        opt = self._check_options()
        if opt:
            return opt

        try:
            partner = request.env['res.partner'].sudo().browse(partner_id)
            if not partner.exists():
                return self._response_success([])

            root = partner._get_loyalty_root() if hasattr(partner, '_get_loyalty_root') else partner
            family_partner_ids = root._get_loyalty_family_partner_ids() if hasattr(root, '_get_loyalty_family_partner_ids') else [partner_id]

            domain = [('partner_id', 'in', family_partner_ids)]
            state = kwargs.get('state')
            if state and state != 'all':
                domain.append(('state', '=', state))

            vouchers = request.env['hlv.loyalty.voucher'].sudo().search(
                domain, order='create_date desc', limit=100
            )
            data = [{
                'id': v.id,
                'code': v.code,
                'name': v.package_id.name if v.package_id else v.code,
                'package_name': v.package_id.name if v.package_id else v.code,
                'state': v.state,
                'reward_type': v.reward_type or 'discount',
                'discount_type': v.discount_type or 'fixed',
                'discount_value': v.discount_value or 0,
                'max_discount_amount': v.max_discount_amount or 0,
                'min_order_amount': v.min_order_amount or 0,
                'date_issued': str(v.date_issued) if v.date_issued else '',
                'date_expiry': str(v.date_expiry) if v.date_expiry else '',
                'expiry_date': str(v.date_expiry) if v.date_expiry else '',
                'gift_product_name': (v.gift_product_id.name if v.gift_product_id else ''),
                'gift_qty': v.gift_qty or 0,
            } for v in vouchers]
            return self._response_success(data)
        except Exception as e:
            _logger.exception("zalo_user_vouchers error: %s", e)
            return self._response_error("LOYALTY_ERROR", str(e), status=500)
