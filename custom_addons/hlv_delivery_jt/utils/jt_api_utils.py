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
            self.api_url = "https://ylopenapi.jtexpress.vn/webopenplatformapi/api/order/addOrder"
        else:
            self.api_url = "https://demoopenapi.jtexpress.vn/webopenplatformapi/api/order/addOrder"

    def _generate_digest(self, biz_content):
        """
        Generate J&T API digest: base64(md5(bizContent + privateKey).hexdigest())
        Note: J&T documentation says md5(bizContent + privateKey)
        """
        data_to_hash = biz_content + self.private_key
        md5_hash = hashlib.md5(data_to_hash.encode('utf-8')).hexdigest()
        digest = base64.b64encode(md5_hash.encode('utf-8')).decode('utf-8')
        return digest

    def add_order(self, biz_params):
        """
        Send Add Order request to J&T
        """
        biz_content = json.dumps(biz_params)
        timestamp = int(time.time() * 1000)
        digest = self._generate_digest(biz_content)

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        # J&T uses form-encoded body for bizContent, apiAccount, digest, timestamp
        payload = {
            'bizContent': biz_content,
            'apiAccount': self.api_account,
            'digest': digest,
            'timestamp': timestamp
        }

        _logger.info("J&T API Request to %s | Account: %s", self.api_url, self.api_account)
        try:
            response = requests.post(self.api_url, data=payload, headers=headers)
            if response.status_code == 200:
                res_json = response.json()
                _logger.info("J&T API Response: %s", res_json)
                return res_json
            else:
                _logger.error("J&T API Error %s: %s", response.status_code, response.text)
                return {'code': 'error', 'msg': f"HTTP Error {response.status_code}"}
        except Exception as e:
            _logger.exception("J&T API Exception: %s", e)
            return {'code': 'error', 'msg': str(e)}
