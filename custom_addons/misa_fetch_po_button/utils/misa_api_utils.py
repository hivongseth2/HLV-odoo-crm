import requests
import logging
from odoo import models
import re
from requests.utils import dict_from_cookiejar
from http.cookiejar import Cookie
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
        # Sử dụng session để duy trì cookie, bao gồm cả HttpOnly
        session = requests.Session()
        
        login_url = "https://amisapp.misa.vn/APIS/AuthenAPI/api/Account/login"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "PostmanRuntime/7.44.1",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        payload = {
            "PassWord": "ThanhLuan1303@",
            "UserName": "thanhluan.hlv@gmail.com",
        }

        # Step 1: Gửi request login
        response = session.post(login_url, headers=headers, json=payload)
        _logger.warning("Đăng nhập MISA với response: %s", response.json())
        _logger.warning("All response headers: %s", dict(response.headers))
        _logger.warning("Full response text: %s", response.text)
        _logger.warning("All cookies in session: %s", dict(session.cookies.get_dict()))  # Log tất cả cookie

        if response.status_code != 200:
            raise Exception(f"Login failed: {response.status_code} - {response.text}")

        # Lấy tất cả cookie từ session (bao gồm HttpOnly)
        cookies_dict = session.cookies.get_dict()
        _logger.warning("Cookies nhận được từ session: %s", cookies_dict)

        # Kiểm tra các cookie cần thiết (dựa vào session)
        x_sessionid = cookies_dict.get("x-sessionid")
        x_tenantid = cookies_dict.get("x-tenantid")

        if not x_sessionid or not x_tenantid:
            raise Exception("Missing required cookies from login response.")

        # Xây dựng cookie header từ session
        cookie_header = ""
        for name, value in cookies_dict.items():
            cookie_header += f"{name}={value}; "
        cookie_header += "x-login-from=basic"

        # Step 2: Gọi HTML page CRM
        crm_url = "https://amisapp.misa.vn/CRM/"
        crm_headers = {
            "Cookie": cookie_header,
            "User-Agent": "PostmanRuntime/7.44.1",
        }
        crm_response = session.get(crm_url, headers=crm_headers)

        if crm_response.status_code != 200:
            raise Exception(f"CRM page fetch failed: {crm_response.status_code}")

        html_content = crm_response.text

        # Step 3: Regex tìm token
        match = re.search(r'"token"\s*:\s*"(?P<token>ey[\w\-\.]+)"', html_content)

        if not match:
            raise Exception("Token not found in CRM HTML")

        return match.group("token")