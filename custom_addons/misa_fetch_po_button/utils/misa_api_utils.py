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
        # return data.get("AccessToken", {}).get("Token", "")
        return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiIxNTQ3Y2M2OS1hOTk1LTQyMWUtOTEzNC03NzM2ZGFiZTZjYjkiLCJ1bmEiOiJBRE1JTiIsImF1dCI6IjAiLCJ1ZW0iOiJob2FuZ2xvbmd2dWNvQGdtYWlsLmNvbSIsIm5iZiI6MTc1MjE2NDA5MiwiZXhwIjoxNzUyMjQ4OTI1LCJpYXQiOjE3NTIxNjQwOTIsImlzcyI6Ik1JU0FKU0MifQ.NGBClyc6mQhPqqTWB0R6TPyG2HRdqdrUeMMsH0mrAAQ"

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
            "Accept-Encoding": "gzip, deflate, br,zstd",
            "Connection": "keep-alive",
            "cookie":"x-culture=vi; x-culture-custom=vi; x-deviceid=3fb273d0-dc87-4dc5-b8f0-be3ac7326cf9; TS01f24fc0=019ba1692d374aa2800e4dd3c3b0c947209c3208135a7706e925464b831498efabe058c022e876f0024124e5793b913070df7bdf8dcaeab0a3c2c127807b6a6a307969db0991221da0d38f06735cb173e45ad7d5fc; _ga_YS0Q78T7TT=GS2.1.s1750565472$o1$g1$t1750565500$j32$l0$h0; _gcl_aw=GCL.1750650790.Cj0KCQjw097CBhDIARIsAJ3-nxf5CAGo6Iss3WGJahKvADR9n_fhjMTsednMtevazje6V0VOuYBjcuwaAp4eEALw_wcB; _gcl_gs=2.1.k1$i1750650785$u212452100; _gcl_au=1.1.786027192.1750650790; _fbp=fb.1.1750650790447.993531807792971466; _ga_VEZHTBQZEB=GS2.1.s1750738193$o3$g0$t1750738200$j53$l0$h0; _ga_325VRLQJQ5=GS2.1.s1750747654$o2$g1$t1750748443$j59$l0$h0; _ga_2B9RDZ4E89=GS2.1.s1751102821$o17$g0$t1751102821$j60$l0$h0; _clck=1rnz2o2%7C2%7Cfx6%7C0%7C2000; _ga_2HDB2Z79W3=GS2.1.s1751197863$o3$g0$t1751197863$j60$l0$h0; _clsk=1t0rssn%7C1751197863946%7C1%7C1%7Cq.clarity.ms%2Fcollect; _gid=GA1.2.1944009150.1751197865; mp_d4b9a27f37c8580e68a0df2684f60882_mixpanel=%7B%22distinct_id%22%3A%20%22acd1603f-e988-4099-ac2a-6538a6a62433%22%2C%22%24device_id%22%3A%20%221979a626dce937-0611e5b707d1ec-46534358-1fa400-1979a626dce937%22%2C%22%24initial_referrer%22%3A%20%22%24direct%22%2C%22%24initial_referring_domain%22%3A%20%22%24direct%22%2C%22__mps%22%3A%20%7B%7D%2C%22__mpso%22%3A%20%7B%7D%2C%22__mpus%22%3A%20%7B%7D%2C%22__mpa%22%3A%20%7B%7D%2C%22__mpu%22%3A%20%7B%7D%2C%22__mpr%22%3A%20%5B%5D%2C%22__mpap%22%3A%20%5B%5D%2C%22%24name%22%3A%20%22NGUY%E1%BB%84N%20TH%C3%80NH%20LU%C3%82N%22%2C%22%24email%22%3A%20%22thanhluan.hlv%40gmail.com%22%2C%22%24user_id%22%3A%20%22acd1603f-e988-4099-ac2a-6538a6a62433%22%2C%22company_code%22%3A%20%223R2PY2F4%22%2C%22isUserAction%22%3A%20true%2C%22feature_category%22%3A%20%22CRM%20Cross%20Sale%22%7D; _ga_8M2C69NVRV=GS2.1.s1751209900$o8$g0$t1751209900$j60$l0$h1614643248; cf_clearance=_tH0pjQMfsbas6Cr9hJZ7DkbNkGmp1E_M_Mdh2twWYs-1751215054-1.2.1.1-745dznRXQmrz_dkExdVLZlkigOlHnRWM4HxnpAGSJMeq8mYtVZsbVetD1rP3L90UtFd9SIOloEvC81rE19WM1y4yR4SjK1DPK799B_OQjeJf3yIYuQEMCpK344Uvg_FjU0gfaX8XqCqUMjpzjCpCzI0BGqRJWfP8bQTZoXLBbQjOOwgKK0sSM3NIJEpDx8zVW.iN8EpF2q4dTAe69XFqaS.SyPIflT8.d90wssNmZL4Jt5U3aHzC4NjLRWsu9tkbRM4P6q2BtuXSr0MuUtoKXGjNPOXc0yk7GyH5.SC5zZP8exn3pS2hYsnwdxe2xAHz5ZLLeFmlenZSmZRH.PfgcCLhG7ZbHbCFm5SGwpPWCVI; _ga_W2GLLHS86T=GS2.1.s1751215708$o4$g0$t1751215708$j60$l0$h0; x-tenantid=47ab503b-99d5-4eb8-aa11-24927abb3585; TS01b5a6fe=019ba1692d2e99bc81c5810436f6bc5c3be19d2e9fd1e8585a8ad41fc26b685cb8076f01c0e2c86649d069289cc61362eaad4df413; _gat_gtag_UA_34323757_8=1; _ga_4N8J1W6EBF=GS2.1.s1751223931$o13$g1$t1751226939$j12$l0$h0; _ga=GA1.1.46578994.1750565329; _ga_0G4YSV5CQ8=GS2.1.s1751223931$o12$g1$t1751226939$j12$l0$h0"
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
    
    


    def get_delivery_number(self, sale_order_id, order_ref=None, token=None):
        # Lấy session từ login
        session = requests.Session()
        _logger.warning("Token lấy được: %s", token)
        _logger.warning("sale_order_id: %s", sale_order_id)
        _logger.warning("order_ref:  %s", order_ref )


        
        # Gửi request GET để lấy delivery number
        api_url = f"https://amisapp.misa.vn/crm/g1/api/business/SaleOrder/FormDataNew/SaleOrder/37/4"
        api_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "PostmanRuntime/7.44.1",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "companycode": "3R2PY2F4",
        }
        api_payload = {
            "ID": str(sale_order_id),
            "MISAEntityState": "2"
        }

        api_response = session.post(api_url, headers=api_headers, json=api_payload)
        _logger.warning("API response headers: %s", dict(api_response.headers))
        _logger.warning("API response text: %s", api_response.text)

        if api_response.status_code != 200:
            raise Exception(f"API call failed: {api_response.status_code} - {api_response.text}")

        # Parse JSON response để lấy delivery number (giả định nằm trong trường DeliveryOrderNumber)
        try:
            response_data = api_response.json()
            delivery_number = response_data.get("Data", {}).get("CurrentData", {}).get("DeliveryOrderNumber")
            
            if not delivery_number:
                delivery_number = order_ref

        except Exception as e:
            print(f"❌ Lỗi khi xử lý response: {e}. Dùng tạm sale_order_id.")
            delivery_number = sale_order_id

        return delivery_number