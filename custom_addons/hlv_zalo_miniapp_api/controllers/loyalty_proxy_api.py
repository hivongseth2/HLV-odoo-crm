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

    # ── Đổi điểm lấy Voucher (Redeem Submit Proxy) ──────────────────────

    @http.route(
        [
            '/api/v1/zalo/loyalty/redeem-submit',
            '/api/v1/zalo/loyalty/redeem/submit',
            '/api/v1/zalo/loyalty/redeem',
        ],
        type='http', auth='public',
        methods=['POST', 'OPTIONS'], csrf=False,
    )
    def zalo_redeem_submit(self, **kwargs):
        """POST /api/v1/zalo/loyalty/redeem-submit
        Body (JSON):
        {
            "partner_id": 42,
            "package_id": 3,
            "phone": "0901234567"
        }
        Proxy đổi thưởng trực tiếp gán account_id chính xác, trừ điểm thực tế vào tài khoản portal.
        """
        opt = self._check_options()
        if opt:
            return opt

        body = self._request_json()
        partner_id = body.get('partner_id') or kwargs.get('partner_id')
        package_id = body.get('package_id') or kwargs.get('package_id')
        phone = body.get('phone') or kwargs.get('phone') or ''

        if not partner_id:
            return self._response_error("MISSING_PARTNER_ID", "Thiếu partner_id", status=400)
        if not package_id:
            return self._response_error("MISSING_PACKAGE_ID", "Thiếu package_id", status=400)

        try:
            partner = request.env['res.partner'].sudo().browse(int(partner_id))
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", status=404)

            root = partner._get_loyalty_root() if hasattr(partner, '_get_loyalty_root') else partner
            package = request.env['hlv.loyalty.voucher.package'].sudo().browse(int(package_id))
            if not package.exists() or not package.active:
                return self._response_error("INVALID_PACKAGE", "Gói voucher không tồn tại hoặc đã ngừng áp dụng", status=400)

            # Tìm đúng tài khoản portal account theo SĐT hoặc tài khoản mặc định
            normalized_phone = self._normalize_vn_phone(phone)
            account = False
            family_ids = root._get_loyalty_family_partner_ids() if hasattr(root, '_get_loyalty_family_partner_ids') else [root.id]
            if normalized_phone and 'hlv.loyalty.portal.account' in request.env:
                account = request.env['hlv.loyalty.portal.account'].sudo().search([
                    ('partner_id', 'in', family_ids),
                    ('portal_phone', '=', normalized_phone),
                    ('active', '=', True),
                ], limit=1)

            if not account and hasattr(root, 'loyalty_portal_account_ids') and root.loyalty_portal_account_ids:
                account = root.loyalty_portal_account_ids.filtered(lambda a: a.is_default)[:1] or root.loyalty_portal_account_ids[:1]

            # Kiểm tra điểm khả dụng
            avail_exchange = 0
            if account:
                avail_exchange = getattr(account, 'loyalty_exchange_available_points', 0) or getattr(account, 'loyalty_exchange_points', 0)
            else:
                avail_exchange = getattr(root, 'loyalty_exchange_available_points', 0) or getattr(root, 'loyalty_exchange_points', 0)

            if avail_exchange < package.points_required:
                return self._response_error(
                    "INSUFFICIENT_POINTS",
                    f"Không đủ điểm đổi thưởng. Cần {package.points_required:,} điểm, bạn còn {avail_exchange:,} điểm.",
                    status=400,
                )

            # Tạo yêu cầu đổi thưởng và thực hiện action_done
            vals = {
                'partner_id': root.id,
                'package_id': package.id,
                'request_type': 'gift',
                'balance_at_request': account.loyalty_exchange_points if account else getattr(root, 'loyalty_exchange_points', 0),
                'company_id': package.company_id.id if package.company_id else request.env.company.id,
            }
            if account:
                vals['account_id'] = account.id

            req = request.env['hlv.loyalty.reward.request'].sudo().create(vals)
            req.action_done()

            # Lấy điểm còn lại sau khi trừ
            remaining_points = 0
            if account:
                remaining_points = account.loyalty_exchange_points
            else:
                remaining_points = getattr(root, 'loyalty_exchange_points', 0)

            return self._response_success({
                'request_id': req.id,
                'request_name': req.name,
                'state': req.state,
                'points_required': req.points_required,
                'voucher_id': req.voucher_id.id if req.voucher_id else None,
                'voucher_code': req.voucher_id.code if req.voucher_id else '',
                'exchange_points': remaining_points,
                'exchange_points_available': remaining_points,
                'exchange_points_remaining': remaining_points,
                'message': 'Nhận mã ưu đãi thành công!',
            })
        except Exception as e:
            _logger.exception("zalo_redeem_submit error: %s", e)
            return self._response_error("REDEEM_ERROR", str(e), status=500)

