# -*- coding: utf-8 -*-
import requests
import logging

_logger = logging.getLogger(__name__)

class GHNApiUtils:
    def __init__(self, token, shop_id, environment='test'):
        self.token = token
        self.shop_id = shop_id
        self.environment = environment
        
        if environment == 'prod':
            self.api_base_url = "https://online-gateway.ghn.vn/shiip/public-api"
        else:
            self.api_base_url = "https://dev-online-gateway.ghn.vn/shiip/public-api"
        
        # Master data endpoints usually don't have /v2
        self.master_data_url = f"{self.api_base_url}/master-data"
        # Shipping and other v2 endpoints
        self.v2_url = f"{self.api_base_url}/v2"

    def _get_headers(self):
        return {
            "Content-Type": "application/json",
            "Token": self.token,
            "ShopId": int(self.shop_id) if self.shop_id else 0
        }

    def get_provinces(self):
        """Fetch all provinces from GHN."""
        url = f"{self.master_data_url}/province"
        try:
            response = requests.get(url, headers={"Token": self.token})
            if response.status_code == 200:
                data = response.json().get("data")
                return data if isinstance(data, list) else []
            _logger.error("GHN get_provinces error: %s", response.text)
        except Exception as e:
            _logger.exception("GHN get_provinces exception: %s", e)
        return []

    def get_districts(self, province_id):
        """Fetch districts for a province."""
        url = f"{self.master_data_url}/district"
        payload = {"province_id": int(province_id)}
        try:
            response = requests.post(url, headers={"Token": self.token}, json=payload)
            if response.status_code == 200:
                data = response.json().get("data")
                return data if isinstance(data, list) else []
            _logger.error("GHN get_districts error: %s", response.text)
        except Exception as e:
            _logger.exception("GHN get_districts exception: %s", e)
        return []

    def get_wards(self, district_id):
        """Fetch wards for a district."""
        url = f"{self.master_data_url}/ward"
        params = {"district_id": int(district_id)}
        try:
            response = requests.get(url, headers={"Token": self.token}, params=params)
            if response.status_code == 200:
                data = response.json().get("data")
                return data if isinstance(data, list) else []
            _logger.error("GHN get_wards error: %s", response.text)
        except Exception as e:
            _logger.exception("GHN get_wards exception: %s", e)
        return []

    def calculate_fee(self, data):
        """
        Calculate shipping fee.
        """
        url = f"{self.v2_url}/shipping-order/fee"
        headers = self._get_headers()
        
        # Ensure shop_id is in the body too
        if 'shop_id' not in data:
            data['shop_id'] = int(self.shop_id)
            
        try:
            response = requests.post(url, headers=headers, json=data)
            res_json = response.json()
            if response.status_code == 200 and res_json.get("code") == 200:
                return {"success": True, "data": res_json.get("data")}
            
            # Specific error handling for "Lỗi lấy thông tin shop"
            error_msg = res_json.get("message") or f"HTTP {response.status_code}"
            if "thông tin shop" in error_msg:
                error_msg += " (Vui lòng kiểm tra lại Shop ID và Token trong Cấu hình)"
                
            return {
                "success": False, 
                "error": error_msg
            }
        except Exception as e:
            _logger.exception("GHN calculate_fee exception: %s", e)
            return {"success": False, "error": str(e)}

    def get_services(self, from_district, to_district):
        """Fetch available services between two districts."""
        url = f"{self.v2_url}/shipping-order/available-services"
        payload = {
            "shop_id": int(self.shop_id),
            "from_district": int(from_district),
            "to_district": int(to_district)
        }
        try:
            response = requests.post(url, headers={"Token": self.token}, json=payload)
            if response.status_code == 200:
                return response.json().get("data", [])
            _logger.error("GHN get_services error: %s", response.text)
        except Exception as e:
            _logger.exception("GHN get_services exception: %s", e)
        return []
