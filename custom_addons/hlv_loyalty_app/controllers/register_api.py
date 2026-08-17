# -*- coding: utf-8 -*-
import json
import logging
import re

from odoo import http
from odoo.http import request, Response

from odoo.addons.hlv_loyalty.controllers.loyalty_api import LoyaltyExternalAPI

_logger = logging.getLogger(__name__)


def _normalize_vn_phone(phone):
    """Bỏ ký tự không phải số; đổi đầu 84 → 0 (chuẩn VN 0xxxxxxxxx)."""
    if not phone:
        return ''
    digits = ''.join(ch for ch in str(phone).strip() if ch.isdigit())
    if digits.startswith('84'):
        digits = '0' + digits[2:]
    return digits


class LoyaltyAppRegisterAPI(http.Controller):
    """API đăng ký tài khoản Loyalty mới cho App Mobile.

    Được đặt riêng trong module hlv_loyalty_app để KHÔNG can thiệp vào
    logic gốc của hlv_loyalty.
    """

    def _cors_headers(self):
        return [
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With"),
        ]

    def _json_response(self, data, status=200):
        return Response(
            json.dumps(data, ensure_ascii=False),
            status=status,
            content_type="application/json; charset=utf-8",
            headers=self._cors_headers(),
        )

    def _json_err(self, message, status=400, code=None):
        payload = {"error": message, "success": False}
        if code:
            payload["code"] = code
        return self._json_response(payload, status=status)

    def _request_json(self):
        try:
            return json.loads(request.httprequest.get_data(as_text=True) or '{}')
        except Exception:
            return {}

    @http.route("/api/v1/loyalty/auth/register", type="http", auth="public",
                methods=["POST", "OPTIONS"], csrf=False, cors="*")
    def auth_register(self, **kwargs):
        """POST /api/v1/loyalty/auth/register

        Tạo mới tài khoản Loyalty (hlv.loyalty.portal.account) cho một SĐT
        chưa có tài khoản.

        Body (JSON):
        {
            "phone": "0901234567",
            "new_password": "matkhau",
            "confirm_password": "matkhau",
            "name" : "Nguyen Van A"   // (tùy chọn) khi phải tạo partner mới
        }

        - Nếu SĐT đã có res.partner trong CRM → gắn tài khoản vào partner sẵn có
          (giữ nguyên điểm/hạng).
        - Nếu chưa có res.partner → tạo partner mới (không bắt buộc is_company).
        - Trả về partner_summary định dạng giống /auth/login để App tự đăng nhập.
        """
        if request.httprequest.method == "OPTIONS":
            return Response(status=200, headers=self._cors_headers())

        body = self._request_json()
        phone = _normalize_vn_phone(kwargs.get("phone") or body.get("phone") or "")
        new_password = (kwargs.get("new_password") or body.get("new_password") or "").strip()
        confirm_password = (kwargs.get("confirm_password") or body.get("confirm_password") or "").strip()
        name = (kwargs.get("name") or body.get("name") or "").strip()

        if not phone or not re.match(r'^0\d{9}$', phone):
            return self._json_err("Số điện thoại không hợp lệ", status=400, code="INVALID_PHONE")
        if not new_password or not confirm_password:
            return self._json_err("Vui lòng điền đầy đủ mật khẩu và xác nhận mật khẩu", status=400, code="MISSING_FIELDS")
        if new_password != confirm_password:
            return self._json_err("Mật khẩu xác nhận không khớp", status=400, code="PASSWORD_MISMATCH")
        if len(new_password) < 6:
            return self._json_err("Mật khẩu phải có ít nhất 6 ký tự", status=400, code="PASSWORD_TOO_SHORT")

        Account = request.env["hlv.loyalty.portal.account"].sudo()
        Partner = request.env["res.partner"].sudo()

        # 1. Không cho đăng ký trùng SĐT đã có tài khoản Loyalty.
        if Account.search([("portal_phone", "=", phone), ("active", "=", True)], limit=1):
            return self._json_err("Số điện thoại đã có tài khoản Loyalty", status=409, code="PHONE_EXISTS")

        # 2. Tìm res.partner sẵn có theo SĐT (không bắt buộc is_company).
        partner = None
        candidates = Partner.search([("phone", "=", phone), ("active", "=", True)], limit=20)
        for cand in candidates:
            root = cand._get_loyalty_root()
            has_acc = Account.search([("partner_id", "=", root.id), ("active", "=", True)], limit=1)
            if not has_acc:
                partner = root
                break
        if not partner and candidates:
            partner = candidates[0]._get_loyalty_root()

        # 3. Chưa có partner → tạo mới.
        if not partner:
            partner = Partner.create({
                "name": name or f"Khách hàng {phone}",
                "phone": phone,
                "is_company": False,
            })

        # 4. Tạo tài khoản Loyalty và gán mật khẩu người dùng đặt.
        try:
            account = Account.create({
                "partner_id": partner.id,
                "username": phone,
                "portal_phone": phone,
            })
            account.set_password(new_password)
        except Exception as exc:
            _logger.exception("register %s failed: %s", phone, exc)
            return self._json_err("Không thể tạo tài khoản Loyalty. Vui lòng thử lại.",
                                  status=400, code="REGISTER_FAILED")

        # 5. Trả summary giống /auth/login (App tự đăng nhập ngay).
        summary = LoyaltyExternalAPI._partner_summary(partner)
        summary["phone"] = account.portal_phone or phone
        summary["account_id"] = account.id
        summary["username"] = account.username
        if account.buyer_name:
            summary["buyer_name"] = account.buyer_name
        summary["is_default_password"] = False

        return self._json_response({
            "success": True,
            "data": summary,
            **summary,
        })
