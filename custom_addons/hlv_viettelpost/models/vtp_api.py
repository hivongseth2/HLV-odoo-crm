# Copyright LGPL-3
import logging
import requests
from odoo import models

_logger = logging.getLogger(__name__)

TIMEOUT = 25

class VTPAPI(models.AbstractModel):
    _name = "vtp.api"
    _description = "Viettel Post API Helper"

    # ---- Config helpers
    def _conf(self, key, default=""):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def _base(self):
        base = self._conf("vtp.api_base", "https://partnerdev.viettelpost.vn/v2")
        return base.rstrip("/")

    def _headers(self, token=None):
        tok = token or self._conf("vtp.token")
        hdrs = {"Content-Type": "application/json"}
        if tok:
            hdrs["Token"] = tok      # VTP expects 'Token' header
        return hdrs

    # ---- Auth
    def vtp_login(self, username=None, password=None):
        username = username or self._conf("vtp.username")
        password = password or self._conf("vtp.password")
        if not username or not password:
            raise ValueError("Thiếu username/password Viettel Post trong Settings.")
        url = f"{self._base()}/user/ownerconnect"
        payload = {"USERNAME": username, "PASSWORD": password}
        r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        try:
            r.raise_for_status()
        except Exception:
            _logger.error("VTP login failed: %s %s", r.status_code, r.text)
            raise
        data = r.json() if r.content else {}
        token = (
            (data.get("data") or {}).get("token")
            or data.get("token")
            or data.get("TOKEN")
        )
        if not token:
            _logger.warning("VTP login response no token: %s", data)
            raise ValueError("Không lấy được token từ Viettel Post")
        self.env["ir.config_parameter"].sudo().set_param("vtp.token", token)
        return token

    # ---- Categories / Address master
    def vtp_list_provinces(self):
        url = f"{self._base()}/categories/listProvince"
        r = requests.get(url, headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    def vtp_list_districts(self, province_id):
        url = f"{self._base()}/categories/listDistrict"
        params = {"provinceId": province_id}
        r = requests.get(url, params=params, headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    def vtp_list_wards(self, district_id):
        url = f"{self._base()}/categories/listWards"
        params = {"districtId": district_id}
        r = requests.get(url, params=params, headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    # ---- Price calculation
    def vtp_calculate_fee(self, payload):
        url = f"{self._base()}/order/getPrice"
        r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        if r.status_code == 401:
            self.vtp_login()
            r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    # ---- Create order
    def vtp_create_order(self, payload):
        url = f"{self._base()}/order/createOrder"
        r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        if r.status_code == 401:
            self.vtp_login()
            r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    # ---- Cancel order
    def vtp_cancel_order(self, order_code, note="Odoo cancel"):
        url = f"{self._base()}/order/cancel"
        payload = {"ORDER_NUMBER": order_code, "NOTE": note}
        r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        if r.status_code == 401:
            self.vtp_login()
            r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    # ---- Label (optional, may return link or bytes depending on account)
    def vtp_get_label(self, order_code):
        url = f"{self._base()}/order/label"
        payload = {"ORDER_NUMBER": order_code}
        r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        if r.status_code == 401:
            self.vtp_login()
            r = requests.post(url, json=payload, headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
