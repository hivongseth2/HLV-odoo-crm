# -*- coding: utf-8 -*-
import requests
import logging

_logger = logging.getLogger(__name__)

class GHNApiUtils:
    def __init__(self, token, shop_id, environment='test'):
        self.token = token
        # Clean shop_id (remove dots/spaces from Odoo formatting)
        self.shop_id = "".join(filter(str.isdigit, str(shop_id))) if shop_id else "0"
        self.environment = environment
        
        if environment == 'prod':
            self.api_base_url = "https://online-gateway.ghn.vn/shiip/public-api"
        else:
            self.api_base_url = "https://dev-online-gateway.ghn.vn/shiip/public-api"
        
        # Shipping and other v2 endpoints
        self.v2_url = f"{self.api_base_url}/v2"
        # Master data endpoints
        self.master_data_url = f"{self.api_base_url}/master-data"
        _logger.info("GHN API Initialized (%s). Base: %s | Master: %s", 
                     self.environment, self.api_base_url, self.master_data_url)

    def _get_headers(self):
        return {
            "Content-Type": "application/json",
            "Token": self.token,
            "ShopId": self.shop_id # Now it's always a clean stringof digits
        }

    def get_provinces(self):
        """Fetch all provinces from GHN."""
        url = f"{self.master_data_url}/province"
        _logger.info("GHN Fetching Provinces from URL: %s", url)
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
        _logger.info("GHN Fetching Districts (Province %s) from URL: %s", province_id, url)
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
        _logger.info("GHN Fetching Wards (District %s) from URL: %s", district_id, url)
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

    def get_shops(self):
        """Fetch all shops associated with the token."""
        url = f"{self.v2_url}/shop/all"
        headers = {"Token": self.token, "Content-Type": "application/json"}
        # GHN docs say this is a POST with empty body or some params
        try:
            response = requests.post(url, headers=headers, json={})
            res_json = response.json()
            if response.status_code == 200 and res_json.get("code") == 200:
                return {"success": True, "data": res_json.get("data")}
            return {"success": False, "error": res_json.get("message")}
        except Exception as e:
            _logger.exception("GHN get_shops exception: %s", e)
            return {"success": False, "error": str(e)}

    def get_services(self, from_district, to_district):
        """Fetch available services between two districts."""
        url = f"{self.v2_url}/shipping-order/available-services"
        headers = self._get_headers()
        
        payload = {
            "shop_id": int(self.shop_id),
            "from_district": int(from_district),
            "to_district": int(to_district)
        }
        _logger.debug("GHN get_services URL: %s, Payload: %s", url, payload)
        try:
            response = requests.post(url, headers=headers, json=payload)
            res_json = response.json()
            if response.status_code == 200 and res_json.get("code") == 200:
                return {"success": True, "data": res_json.get("data")}
            _logger.error("GHN get_services error: %s", response.text)
            return {
                "success": False, 
                "error": res_json.get("message") or f"HTTP {response.status_code}"
            }
        except Exception as e:
            _logger.exception("GHN get_services exception: %s", e)
            return {"success": False, "error": str(e)}

    def create_order(self, data):
        """
        Create a shipping order in GHN.
        """
        url = f"{self.v2_url}/shipping-order/create"
        headers = self._get_headers()
        
        # Ensure shop_id is in the body too
        if 'shop_id' not in data:
            data['shop_id'] = int(self.shop_id)
            
        try:
            response = requests.post(url, headers=headers, json=data)
            res_json = response.json()
            if response.status_code == 200 and res_json.get("code") == 200:
                return {"success": True, "data": res_json.get("data")}
            
            error_msg = res_json.get("message") or f"HTTP {response.status_code}"
            _logger.error("GHN create_order error: %s", response.text)
            return {
                "success": False, 
                "error": error_msg
            }
        except Exception as e:
            _logger.exception("GHN create_order exception: %s", e)
            return {"success": False, "error": str(e)}
