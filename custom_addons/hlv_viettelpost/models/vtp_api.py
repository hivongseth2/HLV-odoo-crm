# Copyright LGPL-3
import logging
import requests
from odoo import models

_logger = logging.getLogger(__name__)
TIMEOUT = 25

class VTPAPI(models.AbstractModel):
    _name = "vtp.api"
    _description = "Viettel Post API Helper"

    def _conf(self, key, default=""):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def _debug(self):
        return (self._conf("vtp.debug") or "").strip().lower() in ("1", "true", "yes")

    def _base(self):
        base = self._conf("vtp.api_base", "https://partnerdev.viettelpost.vn/v2")
        return base.rstrip("/")

    def _headers(self, token=None):
        tok = token or self._conf("vtp.token")
        hdrs = {"Content-Type": "application/json"}
        if tok:
            hdrs["Token"] = tok
        return hdrs

    def vtp_login(self, username=None, password=None):
        import json
        username = username or self._conf("vtp.username")
        password = password or self._conf("vtp.password")
        if not username or not password:
            raise ValueError("Thiếu username/password Viettel Post trong Settings.")
        base = self._base()
        headers = self._headers()

        def _extract_token(resp_json, resp_headers):
            if not isinstance(resp_json, dict):
                return None
            data = resp_json.get("data") if isinstance(resp_json.get("data"), dict) else {}
            candidates = [data.get("token"), data.get("TOKEN"), resp_json.get("token"), resp_json.get("TOKEN")]
            for c in candidates:
                if c:
                    return c
            return resp_headers.get("Token") or resp_headers.get("TOKEN")

        try:
            url1 = f"{base}/user/ownerconnect"
            payload1 = {"USERNAME": username, "PASSWORD": password}
            if self._debug(): _logger.info("[VTP] POST %s payload=%s", url1, payload1)
            r1 = requests.post(url1, json=payload1, headers=headers, timeout=TIMEOUT)
            if self._debug(): _logger.info("[VTP] resp %s: %s", r1.status_code, r1.text)
            r1.raise_for_status()
            j1 = r1.json() if r1.content else {}
            tok = _extract_token(j1, r1.headers)
            if tok:
                self.env["ir.config_parameter"].sudo().set_param("vtp.token", tok)
                return tok
            _logger.warning("[VTP] ownerconnect không trả token: %s", json.dumps(j1, ensure_ascii=False))
        except Exception as e:
            _logger.error("[VTP] ownerconnect lỗi: %s / body=%s", e, getattr(locals().get("r1", None), "text", ""))

        try:
            url2 = f"{base}/user/login"
            payload2 = {"USERNAME": username, "PASSWORD": password}
            if self._debug(): _logger.info("[VTP] POST %s payload=%s", url2, payload2)
            r2 = requests.post(url2, json=payload2, headers=headers, timeout=TIMEOUT)
            if self._debug(): _logger.info("[VTP] resp %s: %s", r2.status_code, r2.text)
            r2.raise_for_status()
            j2 = r2.json() if r2.content else {}
            tok = _extract_token(j2, r2.headers)
            if tok:
                self.env["ir.config_parameter"].sudo().set_param("vtp.token", tok)
                return tok
            _logger.warning("[VTP] login không trả token: %s", json.dumps(j2, ensure_ascii=False))
        except Exception as e:
            _logger.error("[VTP] login lỗi: %s / body=%s", e, getattr(locals().get("r2", None), "text", ""))

        msg = (
            "Không lấy được token từ Viettel Post. Kiểm tra:\n"
            f"- vtp.api_base: {base}\n"
            "- USERNAME/PASSWORD\n"
            "- Tài khoản đã bật quyền API\n"
            "- Endpoint đúng phiên bản /v2\n"
            "Bật System Parameter vtp.debug=1 để xem log chi tiết trong odoo.log."
        )
        raise ValueError(msg)

    def vtp_list_provinces(self):
        url = f"{self._base()}/categories/listProvince"
        if self._debug(): _logger.info("[VTP] GET %s", url)
        r = requests.get(url, headers=self._headers(), timeout=TIMEOUT)
        if self._debug(): _logger.info("[VTP] resp %s: %s", r.status_code, r.text)
        r.raise_for_status()
        return r.json()

    def vtp_list_districts(self, province_id):
        url = f"{self._base()}/categories/listDistrict"
        params = {"provinceId": province_id}
        if self._debug(): _logger.info("[VTP] GET %s params=%s", url, params)
        r = requests.get(url, params=params, headers=self._headers(), timeout=TIMEOUT)
        if self._debug(): _logger.info("[VTP] resp %s: %s", r.status_code, r.text)
        r.raise_for_status()
        return r.json()

    def vtp_list_wards(self, district_id):
        url = f"{self._base()}/categories/listWards"
        params = {"districtId": district_id}
        if self._debug(): _logger.info("[VTP] GET %s params=%s", url, params)
        r = requests.get(url, params=params, headers=self._headers(), timeout=TIMEOUT)
        if self._debug(): _logger.info("[VTP] resp %s: %s", r.status_code, r.text)
        r.raise_for_status()
        return r.json()

    def vtp_calculate_fee(self, payload):
        url = f"{self._base()}/order/getPrice"
        if self._debug(): _logger.info("[VTP] POST %s payload=%s", url, payload)
        r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        if r.status_code == 401:
            if self._debug(): _logger.warning("[VTP] 401 -> login lại")
            self.vtp_login()
            r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        if self._debug(): _logger.info("[VTP] resp %s: %s", r.status_code, r.text)
        r.raise_for_status()
        return r.json()

    def vtp_create_order(self, payload):
        url = f"{self._base()}/order/createOrder"
        if self._debug(): _logger.info("[VTP] POST %s payload=%s", url, payload)
        r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        if r.status_code == 401:
            if self._debug(): _logger.warning("[VTP] 401 -> login lại")
            self.vtp_login()
            r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        if self._debug(): _logger.info("[VTP] resp %s: %s", r.status_code, r.text)
        r.raise_for_status()
        return r.json()

    def vtp_cancel_order(self, order_code, note="Odoo cancel"):
        url = f"{self._base()}/order/cancel"
        payload = {"ORDER_NUMBER": order_code, "NOTE": note}
        if self._debug(): _logger.info("[VTP] POST %s payload=%s", url, payload)
        r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        if r.status_code == 401:
            if self._debug(): _logger.warning("[VTP] 401 -> login lại")
            self.vtp_login()
            r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        if self._debug(): _logger.info("[VTP] resp %s: %s", r.status_code, r.text)
        r.raise_for_status()
        return r.json()

    def vtp_get_label(self, order_code):
        url = f"{self._base()}/order/label"
        payload = {"ORDER_NUMBER": order_code}
        if self._debug(): _logger.info("[VTP] POST %s payload=%s", url, payload)
        r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        if r.status_code == 401:
            if self._debug(): _logger.warning("[VTP] 401 -> login lại")
            self.vtp_login()
            r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        if self._debug(): _logger.info("[VTP] resp %s: %s", r.status_code, r.text)
        r.raise_for_status()
        return r.json()
