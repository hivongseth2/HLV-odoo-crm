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
from odoo.exceptions import UserError
from odoo.http import request

from .base_api import ZaloBaseAPI

_logger = logging.getLogger(__name__)


class ZaloLoyaltyProxyAPI(ZaloBaseAPI, http.Controller):
    """Proxy các endpoint loyalty cho Zalo Mini App."""

    # ── Helper số dư điểm đổi thưởng ────────────────────────────────────

    @staticmethod
    def _reward_balance(account, root):
        """Số dư điểm đổi thưởng, ưu tiên đọc trên tài khoản portal.

        `loyalty_exchange_available_points` = điểm đổi thưởng - điểm đang treo
        ở các yêu cầu `pending`. KHÔNG được fallback sang
        `loyalty_exchange_points` khi giá trị này bằng 0: đó là trường hợp
        khách đã treo hết điểm, fallback sẽ cho phép đổi vượt hạn mức.
        """
        src = account or root
        return {
            'exchange_points': getattr(src, 'loyalty_exchange_points', 0) or 0,
            'pending_reward_points': getattr(src, 'loyalty_reward_pending_points', 0) or 0,
            'exchange_points_available': getattr(src, 'loyalty_exchange_available_points', 0) or 0,
        }

    @staticmethod
    def _insufficient_code(balance):
        return 'PENDING_REWARD_POINTS' if balance['pending_reward_points'] else 'INSUFFICIENT_POINTS'

    @staticmethod
    def _insufficient_message(required, balance):
        msg = (
            f"Không đủ điểm khả dụng. Cần {required:,} điểm, "
            f"bạn còn {balance['exchange_points_available']:,} điểm."
        )
        if balance['pending_reward_points']:
            msg += f" Đang treo {balance['pending_reward_points']:,} điểm trong yêu cầu chờ duyệt."
        return msg

    @staticmethod
    def _reward_request_dict(req):
        return {
            'id': req.id,
            'name': req.name,
            'request_type': req.request_type,
            'points_required': req.points_required,
            'cash_value': req.cash_value,
            'package_id': req.package_id.id if req.package_id else None,
            'package_name': req.package_id.name if req.package_id else '',
            'bank_name': req.bank_name or '',
            'account_number': req.account_number or '',
            'account_name': req.account_name or '',
            'state': req.state,
            'date_request': str(req.date_request) if req.date_request else '',
            'date_done': str(req.date_done) if req.date_done else '',
            'customer_note': req.customer_note or '',
            'voucher_id': req.voucher_id.id if req.voucher_id else None,
            'voucher_code': req.voucher_id.code if req.voucher_id else '',
        }

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
            body = self._request_json()
            phone = kwargs.get('phone') or body.get('phone') or ''
            partner = request.env['res.partner'].sudo().browse(partner_id)
            if not partner.exists():
                return self._response_success([])

            root = partner._get_loyalty_root() if hasattr(partner, '_get_loyalty_root') else partner
            family_partner_ids = root._get_loyalty_family_partner_ids() if hasattr(root, '_get_loyalty_family_partner_ids') else [partner_id]

            normalized_phone = self._normalize_vn_phone(phone or partner.phone or partner.mobile or '')
            account = False
            if normalized_phone and 'hlv.loyalty.portal.account' in request.env:
                account = request.env['hlv.loyalty.portal.account'].sudo().search([
                    ('partner_id', 'in', family_partner_ids),
                    ('portal_phone', '=', normalized_phone),
                    ('active', '=', True),
                ], limit=1)

            if account:
                domain = [
                    '|',
                    ('account_id', '=', account.id),
                    '&', ('account_id', '=', False), ('partner_id', 'in', family_partner_ids),
                ]
            else:
                domain = [('partner_id', 'in', family_partner_ids)]

            state = kwargs.get('state') or body.get('state')
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
            account = self._get_scoped_portal_account(partner, phone)

            # Kiểm tra điểm khả dụng (đã trừ điểm đang treo ở các yêu cầu chờ duyệt)
            balance = self._reward_balance(account, root)
            avail_exchange = balance['exchange_points_available']

            if avail_exchange < package.points_required:
                return self._response_error(
                    self._insufficient_code(balance),
                    self._insufficient_message(package.points_required, balance),
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

    # ── Đổi điểm lấy Refund (Cash Redeem Proxy) ─────────────────────────

    @http.route(
        [
            '/api/v1/zalo/loyalty/refund-submit',
            '/api/v1/zalo/loyalty/refund/submit',
            '/api/v1/zalo/loyalty/redeem-cash',
        ],
        type='http', auth='public',
        methods=['POST', 'OPTIONS'], csrf=False,
    )
    def zalo_refund_submit(self, **kwargs):
        """POST /api/v1/zalo/loyalty/refund-submit

        Body (JSON):
        {
            "partner_id": 42,
            "phone": "0901234567",
            "points_to_redeem": 500,
            "bank_name": "Vietcombank",
            "account_number": "1234567890",
            "account_name": "NGUYEN VAN A",
            "customer_note": "..."
        }

        Tạo yêu cầu đổi điểm lấy refund (`request_type='cash'` trong Odoo).
        Yêu cầu ở trạng thái `pending` chờ admin duyệt — điểm CHƯA bị trừ,
        chỉ bị treo (`loyalty_reward_pending_points`).
        """
        opt = self._check_options()
        if opt:
            return opt

        body = self._request_json()
        partner_id = body.get('partner_id') or kwargs.get('partner_id')
        phone = body.get('phone') or kwargs.get('phone') or ''
        points = self._parse_int(body.get('points_to_redeem') or kwargs.get('points_to_redeem'), 0)
        bank_name = (body.get('bank_name') or '').strip()
        account_number = (body.get('account_number') or '').strip()
        account_name = (body.get('account_name') or '').strip()
        customer_note = (body.get('customer_note') or '').strip()

        if not partner_id:
            return self._response_error("MISSING_PARTNER_ID", "Thiếu partner_id", status=400)
        if points <= 0:
            return self._response_error("INVALID_POINTS", "Số điểm muốn đổi phải lớn hơn 0", status=400)
        if not bank_name or not account_number or not account_name:
            return self._response_error(
                "MISSING_BANK_INFO",
                "Cần điền đầy đủ Ngân hàng, Số tài khoản và Tên chủ tài khoản",
                status=400,
            )

        try:
            partner = request.env['res.partner'].sudo().browse(int(partner_id))
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", status=404)

            root = partner._get_loyalty_root() if hasattr(partner, '_get_loyalty_root') else partner
            account = self._get_scoped_portal_account(partner, phone)
            balance = self._reward_balance(account, root)

            if balance['exchange_points_available'] < points:
                return self._response_error(
                    self._insufficient_code(balance),
                    self._insufficient_message(points, balance),
                    status=400,
                )

            vals = {
                'partner_id': root.id,
                'request_type': 'cash',
                'points_to_redeem': points,
                'bank_name': bank_name,
                'account_number': account_number,
                'account_name': account_name,
                'customer_note': customer_note,
                'balance_at_request': balance['exchange_points'],
                'company_id': request.env.company.id,
            }
            if account:
                vals['account_id'] = account.id

            try:
                req = request.env['hlv.loyalty.reward.request'].sudo().create(vals)
            except UserError as exc:
                # _validate_pending_reward_points() chặn khi vượt điểm khả dụng
                return self._response_error("PENDING_REWARD_POINTS", str(exc), status=400)

            after = self._reward_balance(account, root)
            payload = {
                'request': self._reward_request_dict(req),
                'request_id': req.id,
                'request_name': req.name,
                'state': req.state,
                'points_required': req.points_required,
                'cash_value': req.cash_value,
                'message': 'Đã gửi yêu cầu refund. Vui lòng chờ duyệt.',
            }
            payload.update(after)
            return self._response_success(payload, status=201)
        except Exception as e:
            _logger.exception("zalo_refund_submit error: %s", e)
            return self._response_error("REFUND_ERROR", str(e), status=500)

    # ── Danh sách yêu cầu đổi thưởng ────────────────────────────────────

    @http.route(
        [
            '/api/v1/zalo/loyalty/reward-requests/<int:partner_id>',
            '/api/v1/zalo/loyalty/redeem-requests/<int:partner_id>',
        ],
        type='http', auth='public',
        methods=['GET', 'POST', 'OPTIONS'], csrf=False,
    )
    def zalo_reward_requests(self, partner_id, **kwargs):
        """GET /api/v1/zalo/loyalty/reward-requests/<partner_id>?phone=...&state=pending&limit=50

        Trả về đầy đủ thông tin nhận tiền (bank_name / account_number /
        account_name / date_done) — khác với
        `hlv_loyalty/controllers/loyalty_api.py::list_redeem_requests` vốn
        đang chiếm route `/api/v1/loyalty/redeem/requests` và bỏ các field này.
        """
        opt = self._check_options()
        if opt:
            return opt

        try:
            body = self._request_json()
            phone = kwargs.get('phone') or body.get('phone') or ''
            state = kwargs.get('state') or body.get('state') or 'all'
            limit = min(max(self._parse_int(kwargs.get('limit') or body.get('limit'), 50), 1), 100)

            partner = request.env['res.partner'].sudo().browse(partner_id)
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", status=404)

            root = partner._get_loyalty_root() if hasattr(partner, '_get_loyalty_root') else partner
            account = self._get_scoped_portal_account(partner, phone)
            family_ids = root._get_loyalty_family_partner_ids() if hasattr(root, '_get_loyalty_family_partner_ids') else [root.id]

            domain = [('partner_id', 'in', family_ids)]
            if account:
                # Chỉ hiện yêu cầu của đúng tài khoản portal đang đăng nhập,
                # cộng thêm dữ liệu cũ chưa gắn account_id.
                domain += ['|', ('account_id', '=', account.id), ('account_id', '=', False)]
            if state in ('pending', 'done', 'cancelled'):
                domain.append(('state', '=', state))

            reward_requests = request.env['hlv.loyalty.reward.request'].sudo().search(
                domain, order='date_request desc, id desc', limit=limit
            )
            payload = {'requests': [self._reward_request_dict(r) for r in reward_requests]}
            payload.update(self._reward_balance(account, root))
            return self._response_success(payload)
        except Exception as e:
            _logger.exception("zalo_reward_requests error: %s", e)
            return self._response_error("LOYALTY_ERROR", str(e), status=500)

    # ── Hủy yêu cầu đổi thưởng đang chờ duyệt ───────────────────────────

    @http.route(
        [
            '/api/v1/zalo/loyalty/reward-requests/cancel',
            '/api/v1/zalo/loyalty/redeem-cancel',
        ],
        type='http', auth='public',
        methods=['POST', 'OPTIONS'], csrf=False,
    )
    def zalo_cancel_reward_request(self, **kwargs):
        """POST /api/v1/zalo/loyalty/reward-requests/cancel

        Body: {"partner_id": 42, "request_id": 55, "phone": "0901234567"}
        Hủy yêu cầu `pending` để giải phóng số điểm đang treo.
        """
        opt = self._check_options()
        if opt:
            return opt

        body = self._request_json()
        partner_id = body.get('partner_id') or kwargs.get('partner_id')
        request_id = self._parse_int(body.get('request_id') or kwargs.get('request_id'), 0)
        phone = body.get('phone') or kwargs.get('phone') or ''

        if not partner_id:
            return self._response_error("MISSING_PARTNER_ID", "Thiếu partner_id", status=400)
        if request_id <= 0:
            return self._response_error("MISSING_REQUEST_ID", "Thiếu request_id", status=400)

        try:
            partner = request.env['res.partner'].sudo().browse(int(partner_id))
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", status=404)

            root = partner._get_loyalty_root() if hasattr(partner, '_get_loyalty_root') else partner
            account = self._get_scoped_portal_account(partner, phone)
            family_ids = root._get_loyalty_family_partner_ids() if hasattr(root, '_get_loyalty_family_partner_ids') else [root.id]

            req = request.env['hlv.loyalty.reward.request'].sudo().browse(request_id)
            if not req.exists() or req.partner_id.id not in family_ids:
                return self._response_error("REQUEST_NOT_FOUND", "Yêu cầu đổi thưởng không tồn tại", status=404)
            if req.state != 'pending':
                return self._response_error(
                    "REQUEST_NOT_PENDING", "Chỉ hủy được yêu cầu đang chờ duyệt", status=400
                )

            try:
                req.action_cancel()
            except UserError as exc:
                return self._response_error("CANCEL_FAILED", str(exc), status=400)

            payload = {
                'request': self._reward_request_dict(req),
                'request_id': req.id,
                'request_name': req.name,
                'state': req.state,
                'message': 'Đã hủy yêu cầu đổi thưởng.',
            }
            payload.update(self._reward_balance(account, root))
            return self._response_success(payload)
        except Exception as e:
            _logger.exception("zalo_cancel_reward_request error: %s", e)
            return self._response_error("LOYALTY_ERROR", str(e), status=500)
