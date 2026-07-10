# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import logging
import re
import time
import requests
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
        digits = re.sub(r"\D", "", normalized)
        suffix = digits[1:] if digits.startswith("0") else digits
        parts = [suffix[i:i+3] for i in range(0, len(suffix), 3)]
        return "+84 " + " ".join(parts)

    @staticmethod
    def _search_partner_by_phone(normalized):
        Partner = request.env["res.partner"].sudo()
        digits = re.sub(r"\D", "", normalized)
        suffix = digits[1:] if digits.startswith("0") else digits
        formats = [
            digits,
            "+84" + suffix,
            "+84 " + suffix,
            "+84 " + " ".join(suffix[i:i+3] for i in range(0, len(suffix), 3)),
        ]
        return Partner.search(["|", ("phone", "in", formats), ("mobile", "in", formats)], limit=1)

    @staticmethod
    def _get_secret_key():
        Param = request.env["ir.config_parameter"].sudo()
        key = Param.get_param("zalo_api_secret", "")
        if not key:
            return "hlv_zalo_dev_secret_2026"
        return key

    @staticmethod
    def _generate_token(partner_id, phone):
        secret = ZaloContactAPI._get_secret_key()
        timestamp = int(time.time())
        payload = f"{partner_id}:{phone}:{timestamp}"
        signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return f"{partner_id}.{timestamp}.{signature}"

    @staticmethod
    def _verify_token(token):
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
            expected_sig = hmac.new(secret.encode(), expected_payload.encode(), hashlib.sha256).hexdigest()

            if not hmac.compare_digest(signature, expected_sig):
                return None

            if secret != "hlv_zalo_dev_secret_2026":
                if time.time() - timestamp > 30 * 24 * 3600:
                    return None

            return partner_id
        except (ValueError, IndexError, Exception):
            return None

    def _auth_required(self):
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
    def _do_auth_for_phone(self, phone):
        normalized = self._normalize_vn_phone(phone)
        if not normalized:
            return self._response_error("INVALID_INPUT", "Số điện thoại không hợp lệ")

        PortalAccount = request.env["hlv.loyalty.portal.account"].sudo()
        partner = self._search_partner_by_phone(normalized)

        is_new = False
        if not partner:
            intl_phone = self._intl_phone(normalized)
            partner = request.env["res.partner"].sudo().create({
                "name": f"Zalo {normalized}",
                "phone": intl_phone,
                "mobile": intl_phone,
                "x_is_zalo_account": True,
            })
            is_new = True
        else:
            if not partner.x_is_zalo_account:
                partner.write({"x_is_zalo_account": True})
            if not partner.phone and not partner.mobile:
                intl_phone = self._intl_phone(normalized)
                partner.write({"phone": intl_phone, "mobile": intl_phone})

        portal_account = PortalAccount.search([("portal_phone", "=", normalized)], limit=1)
        if not portal_account:
            PortalAccount.create({
                "partner_id": partner.id,
                "username": f"zalo_{normalized}",
                "portal_phone": normalized,
            })
        elif portal_account.partner_id.id != partner.id:
            portal_account.write({"partner_id": partner.id})

        token = self._generate_token(partner.id, normalized)

        return self._response_success({
            "contact_id": partner.id,
            "name": partner.name,
            "phone": normalized,
            "email": partner.email or "",
            "token": token,
            "is_new": is_new,
        })

    @http.route("/api/v1/zalo/contacts/auth", type="http", auth="public", methods=["POST"], csrf=False)
    def contact_auth(self, **params):
        """Body: {"phone": "090xxxxxxxx"}"""
        try:
            body = self._request_json()
            phone = (body.get("phone") or "").strip()
            if not phone:
                return self._response_error("INVALID_INPUT", "Số điện thoại không được để trống")
            return self._do_auth_for_phone(phone)
        except Exception as e:
            _logger.exception("contact_auth error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # POST /api/v1/zalo/contacts/auth/zalo-phone
    # =========================================================================
    @http.route("/api/v1/zalo/contacts/auth/zalo-phone", type="http", auth="public", methods=["POST"], csrf=False)
    def contact_auth_zalo_phone(self, **params):
        """Body: {"token": "...", "access_token": "..."}"""
        try:
            body = self._request_json()
            phone_token = (body.get("token") or "").strip()
            access_token = (body.get("access_token") or "").strip()

            if not phone_token or not access_token:
                return self._response_error("INVALID_INPUT", "Thiếu token hoặc access_token")

            Param = request.env["ir.config_parameter"].sudo()
            secret_key = Param.get_param("hlv_loyalty.zalo_secret_key") or Param.get_param("zalo.secret_key", "").strip()
            if not secret_key:
                return self._response_error("CONFIG_ERROR", "Thiếu cấu hình Zalo Secret Key trên Odoo", 503)

            zalo_res = requests.get(
                "https://graph.zalo.me/v2.0/me/info",
                headers={
                    "access_token": access_token,
                    "code": phone_token,
                    "secret_key": secret_key,
                },
                timeout=10,
            )
            zalo_data = zalo_res.json()
            if zalo_data.get("error") not in (0, "0", None):
                return self._response_error("ZALO_ERROR", zalo_data.get("message") or "Zalo từ chối token")

            raw_number = ((zalo_data.get("data") or {}).get("number") or zalo_data.get("number") or "")
            normalized = self._normalize_vn_phone(raw_number)
            if not normalized:
                return self._response_error("ZALO_ERROR", "Zalo không trả về số điện thoại")

            return self._do_auth_for_phone(normalized)

        except requests.exceptions.RequestException as e:
            _logger.exception("Zalo graph api error")
            return self._response_error("SERVER_ERROR", "Lỗi kết nối Zalo", 502)
        except Exception as e:
            _logger.exception("contact_auth_zalo_phone error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # POST /api/v1/zalo/contacts/list
    # =========================================================================
    @http.route("/api/v1/zalo/contacts/list", type="http", auth="public", methods=["POST"], csrf=False)
    def contact_list(self, **params):
        """Body: {"limit": 20, "offset": 0}"""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            body = self._request_json()
            limit = self._parse_int(body.get("limit"), 20)
            offset = self._parse_int(body.get("offset"), 0)
            limit = min(max(limit, 1), 100)

            domain = [("x_is_zalo_account", "=", True), ("active", "=", True)]
            partners = request.env["res.partner"].sudo().search(domain, limit=limit, offset=offset, order="id desc")
            total = request.env["res.partner"].sudo().search_count(domain)

            data = [{
                "id": p.id, "name": p.name, "phone": p.phone or "",
                "mobile": p.mobile or "", "email": p.email or "",
                "street": p.street or "", "city": p.city or "",
            } for p in partners]

            return self._response_success({"total": total, "limit": limit, "offset": offset, "contacts": data})
        except Exception as e:
            _logger.exception("contact_list error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # POST /api/v1/zalo/contacts/detail
    # =========================================================================
    @http.route("/api/v1/zalo/contacts/detail", type="http", auth="public", methods=["POST"], csrf=False)
    def contact_detail(self, **params):
        """Body: {"contact_id": 1}"""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"), 0)
            if not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id")

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists() or not partner.active:
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            total_points = 0
            exchange_points = 0
            tier = None
            try:
                total_points = partner.loyalty_total_points or 0
                exchange_points = getattr(partner, 'loyalty_exchange_points', 0)
                if hasattr(partner, 'loyalty_tier_id') and partner.loyalty_tier_id:
                    tier_obj = partner.loyalty_tier_id
                    tier = {
                        "name": tier_obj.name,
                        "icon": tier_obj.icon or "",
                        "image_url": tier_obj.image_url or "",
                    }
            except Exception:
                pass

            data = {
                "id": partner.id, "name": partner.name,
                "phone": partner.phone or "", "mobile": partner.mobile or "",
                "email": partner.email or "", "street": partner.street or "",
                "city": partner.city or "",
                "state": partner.state_id.name if partner.state_id else "",
                "country": partner.country_id.name if partner.country_id else "",
                "zip": partner.zip or "", 
                "total_points": total_points,
                "exchange_points": exchange_points,
                "tier": tier,
            }

            addresses = partner.child_ids.filtered(lambda c: c.type in ("delivery", "other", "invoice"))
            data["addresses"] = [{
                "id": a.id, "name": a.name or "",
                "street": a.street or "", "street2": a.street2 or "",
                "city": a.city or "", "state": a.state_id.name if a.state_id else "",
                "country": a.country_id.name if a.country_id else "",
                "zip": a.zip or "", "phone": a.phone or (partner.phone or ""),
                "type": a.type,
            } for a in addresses]

            return self._response_success(data)
        except Exception as e:
            _logger.exception("contact_detail error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # PUT /api/v1/zalo/contacts/update
    # =========================================================================
    @http.route("/api/v1/zalo/contacts/update", type="http", auth="public", methods=["PUT"], csrf=False)
    def contact_update(self, **params):
        """Body: {"contact_id": 1, "name": "...", "email": "...", "phone": "...", "street": "...", "city": "..."}"""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"), 0)
            if not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id")

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists() or not partner.active:
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            update_vals = {}
            for field in ["name", "email", "street", "city", "zip"]:
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

            return self._response_success({"id": partner.id, "name": partner.name, "message": "Đã cập nhật"})
        except Exception as e:
            _logger.exception("contact_update error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # Addresses API
    # =========================================================================

    # POST /api/v1/zalo/contacts/addresses/list
    @http.route("/api/v1/zalo/contacts/addresses/list", type="http", auth="public", methods=["POST"], csrf=False)
    def address_list(self, **params):
        """Body: {"contact_id": 1}"""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"), 0)
            if not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id")

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            addresses = partner.child_ids.filtered(lambda c: c.type in ("delivery", "other", "invoice"))
            data = [{
                "id": a.id, "name": a.name or "",
                "street": a.street or "", "street2": a.street2 or "",
                "city": a.city or "", "state": a.state_id.name if a.state_id else "",
                "country": a.country_id.name if a.country_id else "",
                "zip": a.zip or "", "phone": a.phone or "",
                "type": a.type,
            } for a in addresses]

            return self._response_success({"addresses": data})
        except Exception as e:
            _logger.exception("address_list error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # POST /api/v1/zalo/contacts/addresses/create
    @http.route("/api/v1/zalo/contacts/addresses/create", type="http", auth="public", methods=["POST"], csrf=False)
    def address_create(self, **params):
        """Body: {"contact_id": 1, "name":"...", "street":"...", "city":"...", "phone":"...", "type":"delivery"}"""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"), 0)
            if not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id")

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            for r in ["street", "city"]:
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
                "id": address.id, "name": address.name or "",
                "street": address.street or "", "street2": address.street2 or "",
                "city": address.city or "", "phone": address.phone or "", "type": address.type,
            }, 201)
        except Exception as e:
            _logger.exception("address_create error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # PUT /api/v1/zalo/contacts/addresses/update
    @http.route("/api/v1/zalo/contacts/addresses/update", type="http", auth="public", methods=["PUT"], csrf=False)
    def address_update(self, **params):
        """Body: {"address_id": 12, "street":"...", "city":"..."}"""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            body = self._request_json()
            addr_id = self._parse_int(body.get("address_id"), 0)
            if not addr_id:
                return self._response_error("INVALID_INPUT", "Thiếu address_id")

            address = request.env["res.partner"].sudo().browse(addr_id)
            if not address.exists():
                return self._response_error("NOT_FOUND", "Địa chỉ không tồn tại", 404)

            update_vals = {}
            for field in ["name", "street", "street2", "city", "zip", "phone", "type"]:
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
                "id": address.id, "name": address.name or "",
                "street": address.street or "", "street2": address.street2 or "",
                "city": address.city or "", "phone": address.phone or "", "type": address.type,
            })
        except Exception as e:
            _logger.exception("address_update error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # POST /api/v1/zalo/contacts/addresses/delete
    @http.route("/api/v1/zalo/contacts/addresses/delete", type="http", auth="public", methods=["POST"], csrf=False)
    def address_delete(self, **params):
        """Body: {"address_id": 12}"""
        try:
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result

            body = self._request_json()
            addr_id = self._parse_int(body.get("address_id"), 0)
            if not addr_id:
                return self._response_error("INVALID_INPUT", "Thiếu address_id")

            address = request.env["res.partner"].sudo().browse(addr_id)
            if not address.exists():
                return self._response_error("NOT_FOUND", "Địa chỉ không tồn tại", 404)

            address.unlink()
            return self._response_success({"message": "Đã xóa địa chỉ"})
        except Exception as e:
            _logger.exception("address_delete error")
            return self._response_error("SERVER_ERROR", str(e), 500)