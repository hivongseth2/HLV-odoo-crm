# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import timedelta, timezone

from odoo import fields, http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class ZaloContactAPI(http.Controller):
    """API Contact (res.partner) cho Zalo Mini App"""

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _response_success(data=None, status=200):
        payload = {"success": True, "data": data or {}}
        return Response(
            json.dumps(payload, default=str),
            status=status,
            content_type="application/json",
        )

    @staticmethod
    def _response_error(code, message, status=400):
        payload = {
            "success": False,
            "error": {"code": code, "message": message},
        }
        return Response(
            json.dumps(payload, default=str),
            status=status,
            content_type="application/json",
        )

    @staticmethod
    def _parse_int(value, default=0):
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _normalize_vn_phone(phone):
        """Chuẩn hóa SĐT Việt Nam về dạng 0xxxxxxxxx."""
        if not phone:
            return ""
        digits = re.sub(r"\D", "", str(phone))
        if len(digits) == 11 and digits.startswith("84"):
            digits = "0" + digits[2:]
        elif len(digits) == 12 and digits.startswith("084"):
            digits = "0" + digits[3:]
        return digits

    @staticmethod
    def _intl_phone(normalized):
        """Chuyển SĐT normalize dạng 0901234567 sang format quốc tế +84 901 234 567."""
        digits = re.sub(r"\D", "", normalized)
        suffix = digits[1:] if digits.startswith("0") else digits  # "901234567"
        parts = [suffix[i:i+3] for i in range(0, len(suffix), 3)]
        return "+84 " + " ".join(parts)

    @staticmethod
    def _search_partner_by_phone(normalized):
        """Tìm res.partner theo SĐT, hỗ trợ mọi format Odoo có thể lưu.
        Giống tinh thần hlv_loyalty: normalize input rồi so sánh."""
        Partner = request.env["res.partner"].sudo()
        digits = re.sub(r"\D", "", normalized)
        suffix = digits[1:] if digits.startswith("0") else digits  # "901234567"

        formats = [
            digits,                          # "0901234567"
            "+84" + suffix,                  # "+84901234567"
            "+84 " + suffix,                 # "+84 901234567"
            "+84 " + " ".join(suffix[i:i+3] for i in range(0, len(suffix), 3)),  # "+84 901 234 567"
        ]

        return Partner.search(["|", ("phone", "in", formats), ("mobile", "in", formats)], limit=1)

    @staticmethod
    def _get_secret_key():
        """Lấy secret key từ config parameter để tạo/xác thực token.
        Trong dev mode, nếu chưa config, trả về key mặc định."""
        Param = request.env["ir.config_parameter"].sudo()
        key = Param.get_param("zalo_api_secret", "")
        if not key:
            # Dev mode: fallback key
            return "hlv_zalo_dev_secret_2026"
        return key

    @staticmethod
    def _generate_token(partner_id, phone):
        """Generate simple HMAC token."""
        secret = ZaloContactAPI._get_secret_key()
        timestamp = int(time.time())
        payload = f"{partner_id}:{phone}:{timestamp}"
        signature = hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return f"{partner_id}.{timestamp}.{signature}"

    @staticmethod
    def _verify_token(token):
        """Verify token, return partner_id if valid, else None.
        In dev mode, if secret is default, skip strict expiry check."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            partner_id = int(parts[0])
            timestamp = int(parts[1])
            signature = parts[2]

            secret = ZaloContactAPI._get_secret_key()
            partner = request.env["res.partner"].sudo().browse(partner_id)
            if not partner.exists():
                return None

            phone = partner.phone or partner.mobile or ""
            phone = ZaloContactAPI._normalize_vn_phone(phone)

            expected_payload = f"{partner_id}:{phone}:{timestamp}"
            expected_sig = hmac.new(
                secret.encode(), expected_payload.encode(), hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(signature, expected_sig):
                return None

            # Token expiry: 30 days (skip if dev secret)
            if secret != "hlv_zalo_dev_secret_2026":
                if time.time() - timestamp > 30 * 24 * 3600:
                    return None

            return partner_id
        except (ValueError, IndexError, Exception):
            return None

    def _auth_required(self):
        """Check Authorization header and return partner_id or error response."""
        auth_header = request.httprequest.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return self._response_error("AUTH_REQUIRED", "Thiếu token xác thực", 401)

        token = auth_header[7:]
        pid = self._verify_token(token)
        if not pid:
            return self._response_error("INVALID_TOKEN", "Token không hợp lệ hoặc đã hết hạn", 401)
        return pid

    @staticmethod
    def _request_json():
        raw = request.httprequest.data or b"{}"
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    # =========================================================================
    # POST /api/v1/zalo/contacts/auth
    # =========================================================================
    @http.route(
        "/api/v1/zalo/contacts/auth",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def contact_auth(self, **params):
        """
        Auth/Đăng ký bằng SĐT.
        Body: {"phone": "090xxxxxxxx"}
        1. Tìm/cập nhật res.partner theo SĐT
        2. Tạo/cập nhật hlv.loyalty.portal.account
        3. Generate token
        """
        try:
            body = self._request_json()
            phone = (body.get("phone") or "").strip()
            if not phone:
                return self._response_error("INVALID_INPUT", "Số điện thoại không được để trống")

            normalized = self._normalize_vn_phone(phone)
            if not normalized:
                return self._response_error("INVALID_INPUT", "Số điện thoại không hợp lệ")

            PortalAccount = request.env["hlv.loyalty.portal.account"].sudo()

            # Find existing partner by phone/mobile (hỗ trợ mọi format)
            partner = self._search_partner_by_phone(normalized)

            is_new = False
            if not partner:
                # Create new partner with intl phone format
                intl_phone = self._intl_phone(normalized)
                partner = request.env["res.partner"].sudo().create({
                    "name": f"Zalo {normalized}",
                    "phone": intl_phone,
                    "mobile": intl_phone,
                    "x_is_zalo_account": True,
                })
                is_new = True
            else:
                # Ensure zalo flag is set
                if not partner.x_is_zalo_account:
                    partner.write({"x_is_zalo_account": True})
                # Update phone if empty
                if not partner.phone and not partner.mobile:
                    intl_phone = self._intl_phone(normalized)
                    partner.write({"phone": intl_phone, "mobile": intl_phone})

            # Find/create portal account
            portal_account = PortalAccount.search([
                ("portal_phone", "=", normalized),
            ], limit=1)

            if not portal_account:
                portal_account = PortalAccount.create({
                    "partner_id": partner.id,
                    "username": f"zalo_{normalized}",
                    "portal_phone": normalized,
                })
            else:
                if portal_account.partner_id.id != partner.id:
                    portal_account.write({"partner_id": partner.id})

            # Generate token
            token = self._generate_token(partner.id, normalized)

            return self._response_success({
                "contact_id": partner.id,
                "name": partner.name,
                "phone": normalized,
                "email": partner.email or "",
                "token": token,
                "is_new": is_new,
            })
        except Exception as e:
            _logger.exception("contact_auth error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # POST /api/v1/zalo/contacts/list
    # =========================================================================
    @http.route(
        "/api/v1/zalo/contacts/list",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def contact_list(self, **params):
        """Danh sách contact có x_is_zalo_account=True."""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            body = self._request_json()
            limit = self._parse_int(body.get("limit", params.get("limit")), 20)
            offset = self._parse_int(body.get("offset", params.get("offset")), 0)
            limit = min(max(limit, 1), 100)

            domain = [("x_is_zalo_account", "=", True), ("active", "=", True)]
            partners = request.env["res.partner"].sudo().search(
                domain, limit=limit, offset=offset, order="id desc"
            )
            total = request.env["res.partner"].sudo().search_count(domain)

            data = []
            for p in partners:
                data.append({
                    "id": p.id,
                    "name": p.name,
                    "phone": p.phone or "",
                    "mobile": p.mobile or "",
                    "email": p.email or "",
                    "street": p.street or "",
                    "city": p.city or "",
                })

            return self._response_success({
                "total": total,
                "limit": limit,
                "offset": offset,
                "contacts": data,
            })
        except Exception as e:
            _logger.exception("contact_list error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # GET /api/v1/zalo/contacts/<id>
    # =========================================================================
    @http.route(
        "/api/v1/zalo/contacts/<int:contact_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def contact_detail(self, contact_id, **params):
        """Chi tiết contact."""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists() or not partner.active:
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            # Get portal points if available
            total_points = 0
            tier_name = ""
            try:
                total_points = partner.loyalty_total_points or 0
            except Exception:
                pass

            data = {
                "id": partner.id,
                "name": partner.name,
                "phone": partner.phone or "",
                "mobile": partner.mobile or "",
                "email": partner.email or "",
                "street": partner.street or "",
                "city": partner.city or "",
                "state": partner.state_id.name if partner.state_id else "",
                "country": partner.country_id.name if partner.country_id else "",
                "zip": partner.zip or "",
                "total_points": total_points,
            }

            # Include addresses
            addresses = partner.child_ids.filtered(
                lambda c: c.type in ("delivery", "other", "invoice")
            )
            data["addresses"] = [
                {
                    "id": a.id,
                    "name": a.name or a.commercial_partner_name or "",
                    "street": a.street or "",
                    "street2": a.street2 or "",
                    "city": a.city or "",
                    "state": a.state_id.name if a.state_id else "",
                    "country": a.country_id.name if a.country_id else "",
                    "zip": a.zip or "",
                    "phone": a.phone or (partner.phone or ""),
                    "type": a.type,
                }
                for a in addresses
            ]

            return self._response_success(data)
        except Exception as e:
            _logger.exception("contact_detail error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # PUT /api/v1/zalo/contacts/<id>
    # =========================================================================
    @http.route(
        "/api/v1/zalo/contacts/<int:contact_id>",
        type="http",
        auth="public",
        methods=["PUT"],
        csrf=False,
    )
    def contact_update(self, contact_id, **params):
        """Cập nhật thông tin cá nhân."""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists() or not partner.active:
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            body = self._request_json()
            update_vals = {}
            allowed_fields = ["name", "email", "street", "city", "zip"]

            for field in allowed_fields:
                if field in body:
                    update_vals[field] = body[field]

            if "phone" in body and body["phone"]:
                normalized = self._normalize_vn_phone(body["phone"])
                if normalized:
                    intl_phone = self._intl_phone(normalized)
                    update_vals["phone"] = intl_phone
                    update_vals["mobile"] = intl_phone

            if update_vals:
                partner.write(update_vals)

            # Return updated detail
            return self.contact_detail(contact_id)
        except Exception as e:
            _logger.exception("contact_update error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # Addresses sub-resource
    # =========================================================================

    # GET /api/v1/zalo/contacts/<id>/addresses
    @http.route(
        "/api/v1/zalo/contacts/<int:contact_id>/addresses",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def address_list(self, contact_id, **params):
        """Danh sách địa chỉ của contact."""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            addresses = partner.child_ids.filtered(
                lambda c: c.type in ("delivery", "other", "invoice")
            )

            data = [
                {
                    "id": a.id,
                    "name": a.name or "",
                    "street": a.street or "",
                    "street2": a.street2 or "",
                    "city": a.city or "",
                    "state": a.state_id.name if a.state_id else "",
                    "country": a.country_id.name if a.country_id else "",
                    "zip": a.zip or "",
                    "phone": a.phone or "",
                    "type": a.type,
                }
                for a in addresses
            ]

            return self._response_success({"addresses": data})
        except Exception as e:
            _logger.exception("address_list error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # POST /api/v1/zalo/contacts/<id>/addresses
    @http.route(
        "/api/v1/zalo/contacts/<int:contact_id>/addresses",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def address_create(self, contact_id, **params):
        """Thêm địa chỉ mới cho contact."""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            body = self._request_json()
            required = ["street", "city"]
            for r in required:
                if r not in body or not body[r]:
                    return self._response_error("INVALID_INPUT", f"Thiếu trường bắt buộc: {r}")

            vals = {
                "parent_id": contact_id,
                "type": body.get("type", "delivery"),
                "name": body.get("name", partner.name),
                "street": body["street"],
                "street2": body.get("street2", ""),
                "city": body["city"],
                "state_id": body.get("state_id"),
                "country_id": body.get("country_id"),
                "zip": body.get("zip", ""),
                "phone": body.get("phone", partner.phone or ""),
            }

            if vals.get("state_id"):
                state = request.env["res.country.state"].sudo().browse(vals["state_id"])
                vals["state_id"] = state.id if state.exists() else False
            if vals.get("country_id"):
                country = request.env["res.country"].sudo().browse(vals["country_id"])
                vals["country_id"] = country.id if country.exists() else False

            address = request.env["res.partner"].sudo().create(vals)

            return self._response_success({
                "id": address.id,
                "name": address.name or "",
                "street": address.street or "",
                "street2": address.street2 or "",
                "city": address.city or "",
                "phone": address.phone or "",
                "type": address.type,
            }, 201)
        except Exception as e:
            _logger.exception("address_create error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # PUT /api/v1/zalo/contacts/<id>/addresses/<addr_id>
    @http.route(
        "/api/v1/zalo/contacts/<int:contact_id>/addresses/<int:addr_id>",
        type="http",
        auth="public",
        methods=["PUT"],
        csrf=False,
    )
    def address_update(self, contact_id, addr_id, **params):
        """Sửa địa chỉ."""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            address = request.env["res.partner"].sudo().browse(addr_id)
            if not address.exists() or address.parent_id.id != contact_id:
                return self._response_error("NOT_FOUND", "Địa chỉ không tồn tại", 404)

            body = self._request_json()
            update_vals = {}
            allowed = ["name", "street", "street2", "city", "zip", "phone", "type"]
            for field in allowed:
                if field in body:
                    update_vals[field] = body[field]

            if "state_id" in body:
                state = request.env["res.country.state"].sudo().browse(body["state_id"])
                update_vals["state_id"] = state.id if state.exists() else False
            if "country_id" in body:
                country = request.env["res.country"].sudo().browse(body["country_id"])
                update_vals["country_id"] = country.id if country.exists() else False

            if update_vals:
                address.write(update_vals)

            return self._response_success({
                "id": address.id,
                "name": address.name or "",
                "street": address.street or "",
                "street2": address.street2 or "",
                "city": address.city or "",
                "phone": address.phone or "",
                "type": address.type,
            })
        except Exception as e:
            _logger.exception("address_update error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # DELETE /api/v1/zalo/contacts/<id>/addresses/<addr_id>
    @http.route(
        "/api/v1/zalo/contacts/<int:contact_id>/addresses/<int:addr_id>",
        type="http",
        auth="public",
        methods=["DELETE"],
        csrf=False,
    )
    def address_delete(self, contact_id, addr_id, **params):
        """Xóa địa chỉ."""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            address = request.env["res.partner"].sudo().browse(addr_id)
            if not address.exists() or address.parent_id.id != contact_id:
                return self._response_error("NOT_FOUND", "Địa chỉ không tồn tại", 404)

            address.unlink()
            return self._response_success({"message": "Đã xóa địa chỉ"})
        except Exception as e:
            _logger.exception("address_delete error")
            return self._response_error("SERVER_ERROR", str(e), 500)