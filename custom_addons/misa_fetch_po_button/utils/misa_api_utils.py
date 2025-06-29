import requests
import logging
from odoo import models
import re
from requests.utils import dict_from_cookiejar

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

        # Step 1: Gửi request login
        login_url = "https://amisapp.misa.vn/APIS/AuthenAPI/api/Account/login"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._get_misa_token()}",
        }
        payload = {
            "Password": "ThanhLuan1303@",
            "UserName": "thanhluan.hlv@gmail.com",
        }

        response = requests.post(login_url, headers=headers, json=payload)

        _logger.warning("===> STATUS LOGIN: %s", response.status_code)
        _logger.warning("===> RESPONSE JSON: %s", response.text)

        if response.status_code != 200:
            raise Exception(f"Login failed: {response.status_code} - {response.text}")

        # Step 2: Log tất cả cookies rõ ràng
        _logger.warning("===> COOKIE LIST:")
        for cookie in response.cookies:
            _logger.warning("  - %s=%s (domain=%s, path=%s)", cookie.name, cookie.value, cookie.domain, cookie.path)

        # Step 3: Check cookie quan trọng
        cookies_dict = {cookie.name: cookie.value for cookie in response.cookies}
        required_cookies = ['x-sessionid', 'x-tenantid']
        missing = [k for k in required_cookies if k not in cookies_dict]

        if missing:
            raise Exception(f"Missing required cookies: {', '.join(missing)}")

        # Step 4: Build full cookie header
        cookie_header = "; ".join(
            f"{cookie.name}={cookie.value}" for cookie in response.cookies
        )
        _logger.warning("===> BUILT COOKIE HEADER: %s", cookie_header)

        # Step 5: Gọi trang HTML CRM
        crm_url = "https://amisapp.misa.vn/CRM/"
        crm_headers = {
            "Cookie": cookie_header,
            "User-Agent": "Mozilla/5.0",
        }

        crm_response = requests.get(crm_url, headers=crm_headers)
        _logger.warning("===> CRM PAGE STATUS: %s", crm_response.status_code)

        if crm_response.status_code != 200:
            raise Exception(f"CRM page fetch failed: {crm_response.status_code}")

        # Step 6: Regex token trong HTML
        html_content = crm_response.text
        match = re.search(r'"token"\s*:\s*"(?P<token>ey[\w\-\.]+)"', html_content)

        if not match:
            raise Exception("Token not found in CRM HTML")

        token = match.group("token")
        _logger.warning("===> CRM TOKEN FOUND: %s", token)

        return token
