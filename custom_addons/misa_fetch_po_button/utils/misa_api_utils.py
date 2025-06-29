import requests
import logging
from odoo import models
import re
_logger = logging.getLogger(__name__)

class MisaApiUtils(models.AbstractModel):
    _name = 'misa.api.utils'
    _description = 'MISA API Utilities'

    def _get_misa_token(self):
        """Get MISA access token"""
        login_url = "https://amisapp.misa.vn/APIS/AuthenAPI/api/Account/login"
        payload = {
            "UserName": "Hoanglongvuco@gmail.com",
            "Password": "Hoanglongvu@2025"
        }
        headers = {"content-type": "application/json"}
        response = requests.post(login_url, json=payload, headers=headers)
        _logger.warning("Đăng nhập MISA với user: %s", response.json())
        if response.status_code != 200:
            raise Exception("❌ Lỗi đăng nhập MISA")
        data = response.json().get("Data", {})
        return data.get("AccessToken", {}).get("Token", "")

    def _fetch_with_retry(self, url, headers, payload):
        """Fetch API with retry on token expiration"""
        response = requests.post(url, headers=headers, json=payload)
        _logger.info("Response text: %s", response.text)
        if response.status_code == 401:
            _logger.warning("🔁 Token hết hạn, đang đăng nhập lại...")
            new_token = self._get_misa_token()
            _logger.info("🔑 Đăng nhập thành công, token mới: %s", new_token)
            headers["Authorization"] = f"Bearer {new_token}"
            response = requests.post(url, headers=headers, json=payload)
        return response


    def _fetch_login_crm_token(self):
        """Fetch CRM token for MISA"""
        login_url = "https://amisapp.misa.vn/APIS/AuthenAPI/api/Account/login"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._get_misa_token()}",
        }
        payload = {
            "userName": "ThanhLuan1303@",
            "password": "thanhluan.hlv@gmail.com",
        }

        # Step 1: Gửi request login
        response = requests.post(login_url, headers=headers, json=payload)

        if response.status_code != 200:
            raise Exception(f"Login failed: {response.status_code} - {response.text}")

        # Step 2: Parse từ raw Set-Cookie headers
        set_cookies = response.headers.getlist('Set-Cookie') if hasattr(response.headers, 'getlist') else response.headers.get('Set-Cookie', '').split(',')

        x_sessionid = None
        x_tenantid = None

        for cookie in set_cookies:
            if 'x-sessionid=' in cookie:
                x_sessionid = re.search(r'x-sessionid=([^;]+)', cookie).group(1)
            elif 'x-tenantid=' in cookie:
                x_tenantid = re.search(r'x-tenantid=([^;]+)', cookie).group(1)

        if not x_sessionid or not x_tenantid:
            raise Exception("Missing required cookies from login response.")

        cookie_header = (
            f"x-sessionid={x_sessionid}; "
            f"x-tenantid={x_tenantid}; "
            f"x-login-from=basic"
        )

        # Step 3: Gọi HTML page CRM
        crm_url = "https://amisapp.misa.vn/CRM/"
        crm_headers = {
            "Cookie": cookie_header,
            "User-Agent": "Mozilla/5.0",
        }

        crm_response = requests.get(crm_url, headers=crm_headers)

        if crm_response.status_code != 200:
            raise Exception(f"CRM page fetch failed: {crm_response.status_code}")

        html_content = crm_response.text

        # Step 4: Regex tìm token
        match = re.search(r'"token"\s*:\s*"(?P<token>ey[\w\-\.]+)"', html_content)

        if not match:
            raise Exception("Token not found in CRM HTML")

        return match.group("token")