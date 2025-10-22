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
        """Lấy Token VTP (v2). Một số tài khoản yêu cầu 2 bước:
        1) /user/ownerconnect
        2) Nếu không có token, thử /user/login
        Trả token và lưu vào ir.config_parameter.
        """
        import json
        import requests

        username = username or self._conf("vtp.username")
        password = password or self._conf("vtp.password")
        if not username or not password:
            raise ValueError("Thiếu username/password Viettel Post trong Settings.")

        base = self._base()
        headers = self._headers()

        def _extract_token(resp_json, resp_headers):
            """Cố gắng lấy token từ nhiều kiểu trả về khác nhau."""
            if not resp_json:
                return None
            data = resp_json.get("data") if isinstance(resp_json, dict) else None
            candidates = [
                (data or {}).get("token"),
                (data or {}).get("TOKEN"),
                resp_json.get("token"),
                resp_json.get("TOKEN"),
            ]
            for c in candidates:
                if c:
                    return c
            # Một số triển khai trả token ở header
            return resp_headers.get("Token") or resp_headers.get("TOKEN")

        # --- Thử 1: ownerconnect
        try:
            url1 = f"{base}/user/ownerconnect"
            payload1 = {"USERNAME": username, "PASSWORD": password}
            r1 = requests.post(url1, json=payload1, headers=headers, timeout=TIMEOUT)
            r1.raise_for_status()
            j1 = r1.json() if r1.content else {}
            tok = _extract_token(j1, r1.headers)
            if tok:
                self.env["ir.config_parameter"].sudo().set_param("vtp.token", tok)
                return tok
            # nếu server trả lời nhưng không có token -> ghi log chi tiết
            _logger.warning("VTP ownerconnect không trả token: %s", json.dumps(j1, ensure_ascii=False))
        except Exception as e:
            _logger.error("VTP ownerconnect lỗi: %s / body=%s", e, getattr(r1, "text", ""))

        # --- Thử 2: login (một số tài khoản yêu cầu gọi login)
        try:
            url2 = f"{base}/user/login"
            payload2 = {"USERNAME": username, "PASSWORD": password}
            r2 = requests.post(url2, json=payload2, headers=headers, timeout=TIMEOUT)
            r2.raise_for_status()
            j2 = r2.json() if r2.content else {}
            tok = _extract_token(j2, r2.headers)
            if tok:
                self.env["ir.config_parameter"].sudo().set_param("vtp.token", tok)
                return tok
            _logger.warning("VTP login không trả token: %s", json.dumps(j2, ensure_ascii=False))
        except Exception as e:
            _logger.error("VTP login lỗi: %s / body=%s", e, getattr(r2, "text", ""))

        # Không lấy được token -> bắn thông báo chi tiết
        msg = (
            "Không lấy được token từ Viettel Post. Kiểm tra giúp:\n"
            f"- vtp.api_base: {base}\n"
            "- USERNAME/PASSWORD đúng chưa\n"
            "- Tài khoản đã được bật quyền API trên cổng đối tác (partnerdev/partner) chưa\n"
            "- Endpoint đúng phiên bản /v2 (VD: https://partnerdev.viettelpost.vn/v2)\n"
            "Xem thêm log server (VTP ownerconnect/login trả về gì) trong odoo.log."
        )
        raise ValueError(msg)


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
