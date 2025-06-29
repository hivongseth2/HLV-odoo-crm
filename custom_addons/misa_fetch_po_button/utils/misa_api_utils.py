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

        response = requests.post(login_url, headers=headers, json=payload)

        # Log toàn bộ headers
        logging.warning("===> RESPONSE HEADERS <===")
        for k, v in response.headers.items():
            logging.warning(f"{k}: {v}")

        if response.status_code != 200:
            raise Exception(f"Login failed: {response.status_code} - {response.text}")

        # Step 2: Parse từ Set-Cookie
        set_cookie_header = response.headers.get("Set-Cookie", "")
        logging.warning(f"===> Raw Set-Cookie: {set_cookie_header}")

        # Nếu có nhiều Set-Cookie thì split từng cái
        set_cookies = set_cookie_header.split('\n') if '\n' in set_cookie_header else set_cookie_header.split(',')

        x_sessionid = None
        x_tenantid = None

        for cookie in set_cookies:
            if 'x-sessionid=' in cookie:
                match = re.search(r'x-sessionid=([^;]+)', cookie)
                if match:
                    x_sessionid = match.group(1)
            elif 'x-tenantid=' in cookie:
                match = re.search(r'x-tenantid=([^;]+)', cookie)
                if match:
                    x_tenantid = match.group(1)

        logging.warning(f"x-sessionid: {x_sessionid}")
        logging.warning(f"x-tenantid: {x_tenantid}")

        if not x_sessionid or not x_tenantid:
            raise Exception("Missing required cookies from login response.")