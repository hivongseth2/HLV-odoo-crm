# -*- coding: utf-8 -*-
import hashlib
import base64
import json
import requests
import time
import logging

_logger = logging.getLogger(__name__)

class JTApiUtils:
    def __init__(self, api_account, private_key, environment='test'):
        self.api_account = api_account
        self.private_key = private_key
        self.environment = environment

        if environment == 'prod':
            self.base_url = "https://ylopenapi.jtexpress.vn/webopenplatformapi/api"
        else:
            self.base_url = "https://demoopenapi.jtexpress.vn/webopenplatformapi/api"

    def _get_url(self, service_type):
        """
        Get URL based on service type.
        service_type: 'addOrder', 'cancelOrder', or 'getComCost'
        """
        if service_type == 'getComCost':
            return f"{self.base_url}/spmComCost/{service_type}"
        elif service_type == 'printOrders':
            return f"{self.base_url}/print/{service_type}"
        elif service_type == 'trace':
            return f"{self.base_url}/logistics/trace"
        else:
            return f"{self.base_url}/order/{service_type}"

    def _generate_digest(self, biz_content):
        """
        Generate MD5 digest for J&T API authentication.
        """
        # --- LOGGING ---
        # _logger.info(f"J&T DEBUG - biz_content: {biz_content}")
        # _logger.info(f"J&T DEBUG - private_key: {self.private_key}") 
        # ---------------

        data_to_hash = biz_content + self.private_key
        
        # Log chuỗi trước khi hash để đảm bảo không sai encoding
        # _logger.debug(f"J&T DEBUG - String to hash: {data_to_hash}")

        md5_hash = hashlib.md5(data_to_hash.encode('utf-8')).digest()
        digest = base64.b64encode(md5_hash).decode('utf-8')
        
        return digest
    
    def _send_request(self, service_type, biz_params):
        """
        Generic method to send requests to J&T
        """
        url = self._get_url(service_type)
        
        # --- 1. LOG INPUT RAW ---
        # _logger.info("========== J&T REQUEST START ==========")
        # _logger.info("Step 1 - biz_params (Dict): %s", biz_params)

        # Tạo biz_content (JSON string minified)
        biz_content = json.dumps(biz_params, separators=(',', ':'), ensure_ascii=False)
        
        # --- 2. LOG STRING TO HASH ---
        # Quan trọng: Kiểm tra chuỗi này xem có đúng là chuỗi được dùng để tạo digest không
        # _logger.info("Step 2 - biz_content (For Digest): %s", biz_content)

        timestamp = int(time.time() * 1000)
        digest = self._generate_digest(biz_content)

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'apiAccount': str(self.api_account),
            'digest': digest,
            'timestamp': str(timestamp)
        }

        payload = {
            'bizContent': biz_content
        }

        # --- 3. LOG FULL REQUEST (HEADERS & PAYLOAD) ---
        # Log chi tiết để kiểm tra lần cuối trước khi bắn request
        try:
            # _logger.info("----------- FINAL REQUEST DETAILS -----------")
            # _logger.info(f"Target URL: {url}")
            
            # Dùng json.dumps indent=2 để in ra cho đẹp, dễ đọc
            # _logger.info("HEADERS Sent:\n%s", json.dumps(headers, indent=2))
            
            # Lưu ý: Trong payload, 'bizContent' là một chuỗi JSON (string), không phải dict
            # _logger.info("PAYLOAD Sent:\n%s", json.dumps(payload, indent=2))
            _logger.info("---------------------------------------------")
        except Exception:
            # Fallback nếu không json dump được (tránh lỗi làm dừng chương trình)
            _logger.info("HEADERS Sent: %s", headers)
            _logger.info("PAYLOAD Sent: %s", payload)
        # -----------------------------------------------

        try:
            response = requests.post(url, data=payload, headers=headers)
            
            if response.status_code == 200:
                res_json = response.json()
                # _logger.info("J&T API Response: %s", res_json)
                # _logger.info("========== J&T REQUEST END ==========")
                return res_json
            else:
                # _logger.error("J&T API Error %s: %s", response.status_code, response.text)
                return {'code': 'error', 'msg': f"HTTP Error {response.status_code}"}
        except Exception as e:
            _logger.exception("J&T API Exception: %s", e)
            return {'code': 'error', 'msg': str(e)}
    def add_order(self, biz_params):
        """
        Send Add Order request to J&T
        """
        return self._send_request('addOrder', biz_params)

    def cancel_order(self, biz_params):
        """
        Send Cancel Order request to J&T
        """
        return self._send_request('cancelOrder', biz_params)

    def calculate_fee(self, biz_params):
        """
        Calculate shipping fee from J&T
        """
        return self._send_request('getComCost', biz_params)

    def print_label(self, biz_params):
        """
        Print shipping label from J&T
        Returns base64 encoded PDF content
        """
        return self._send_request('printOrder', biz_params)

    def print_bulk_labels(self, biz_params):
        """
        Print bulk labels from J&T
        Returns a URL to the combined PDF
        """
        return self._send_request('printOrders', biz_params)

    def trace_order(self, biz_params):
        """
        Trace order status from J&T
        http://domain/webopenplatformapi/api/logistics/trace
        """
        # The URL for trace is slightly different (/logistics/trace instead of /order/...)
        # We need to handle this URL construction.
        # Check _get_url implementation or override it locally.
        # Actually _get_url uses service_type. 
        # If we pass 'trace', it goes to /order/trace which is WRONG based on docs.
        # Docs say: /webopenplatformapi/api/logistics/trace
        
        # Let's adjust _get_url first if needed, or handle it here.
        # Looking at _get_url:
        # return f"{self.base_url}/order/{service_type}"
        
        # We should update _get_url to handle 'trace'
        return self._send_request('trace', biz_params)

    @staticmethod
    def search_address(auth_token, search_key, data_type=3):
        """
        Search address using J&T VIP API.
        This API uses different authentication (authToken header instead of digest).
        
        Args:
            auth_token: The authToken from J&T VIP portal
            search_key: The address string to search
            data_type: 3 = search all levels (province, district, ward, street)
        
        Returns:
            dict: API response with matched addresses
            
        Response format:
        {
            "code": 1,
            "msg": "请求成功",
            "data": [{
                "provinceName": "Hồ Chí Minh",
                "provinceId": 74,
                "cityName": "Quận Tân Phú",
                "cityId": 768,
                "areaName": "Phường Tân Quý-028QTP04",
                "areaId": 1679,
                "streetName": "...",
                "streetId": null
            }],
            "succ": true
        }
        """
        url = "https://ylvipapi.jtexpress.vn/api/region/getAreaStreetBySearchKey"
        
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'authToken': auth_token,
            'langType': 'VN',
            'routeName': 'OrderCreate'
        }
        
        params = {
            'searchKey': search_key,
            'dataType': data_type
        }
        
        try:
            # _logger.info("J&T Address Search | URL: %s | searchKey: %s", url, search_key)
            response = requests.get(url, params=params, headers=headers)
            
            if response.status_code == 200:
                res_json = response.json()
                # _logger.info("J&T Address Search Response: %s", res_json)
                return res_json
            else:
                # _logger.error("J&T Address Search Error %s: %s", response.status_code, response.text)
                return {'code': 'error', 'msg': f"HTTP Error {response.status_code}", 'data': []}
        except Exception as e:
            # _logger.exception("J&T Address Search Exception: %s", e)
            return {'code': 'error', 'msg': str(e), 'data': []}

