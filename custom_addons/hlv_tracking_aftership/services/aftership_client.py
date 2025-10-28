# -*- coding: utf-8 -*-
import requests
import logging

_logger = logging.getLogger(__name__)

AFTERSHIP_API_BASE = "https://api.aftership.com/tracking/2025-07"


class AfterShipClient:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("AfterShip API key is required")
        self.headers = {
            "Content-Type": "application/json",
            "as-api-key": api_key,
        }

    def create_tracking(self, slug: str, tracking_number: str, title: str = None):
        payload = {
            "tracking_number": (tracking_number or "").strip(),
            "slug": (slug or "").strip(),
        }
        if title:
            payload["title"] = title

        url = f"{AFTERSHIP_API_BASE}/trackings"
        r = requests.post(url, json=payload, headers=self.headers, timeout=20)

        if r.status_code in (200, 201):
            return r.json()

        try:
            data = r.json()
        except Exception:
            data = None

        if r.status_code == 400 and isinstance(data, dict):
            meta = (data.get("meta") or {})
            if str(meta.get("code")) == "4003":
                return data

        if r.status_code == 409:
            _logger.info("AfterShip: tracking existed, using current one: %s", r.text)
            return r.json()

        if not r.ok:
            _logger.error("AfterShip create failed [%s]: %s", r.status_code, r.text)
            r.raise_for_status()

        return r.json()

    def get_tracking_by_id(self, tracking_id: str, lang: str = "vi"):
        lang_query = f"?lang={lang}" if lang else ""
        url = f"{AFTERSHIP_API_BASE}/trackings/{tracking_id}{lang_query}"
        r = requests.get(url, headers=self.headers, timeout=20)
        r.raise_for_status()
        return r.json()

    def get_tracking_by_number(self, slug: str, tracking_number: str, lang: str = "vi"):
        lang_query = f"?lang={lang}" if lang else ""
        url = f"{AFTERSHIP_API_BASE}/trackings/{slug}/{tracking_number}{lang_query}"
        r = requests.get(url, headers=self.headers, timeout=20)
        r.raise_for_status()
        return r.json()

    def register_webhook(self, webhook_url: str):
        """
        Đăng ký webhook URL với AfterShip
        
        AfterShip sẽ gửi POST request đến URL này khi có cập nhật tracking.
        Chỉ cần đăng ký 1 lần cho toàn bộ hệ thống.
        
        Args:
            webhook_url: URL endpoint để nhận webhook (ví dụ: https://yourdomain.com/aftership/webhook)
        
        Returns:
            dict: Response từ AfterShip API
        """
        payload = {
            "url": webhook_url
        }
        
        url = f"{AFTERSHIP_API_BASE}/webhooks"
        r = requests.post(url, json=payload, headers=self.headers, timeout=20)
        
        if r.status_code in (200, 201):
            _logger.info(f"Webhook registered successfully: {webhook_url}")
            return r.json()
        
        # Nếu webhook đã tồn tại (409 conflict), coi như thành công
        if r.status_code == 409:
            _logger.info(f"Webhook already exists: {webhook_url}")
            return r.json() if r.content else {"status": "already_exists"}
        
        if not r.ok:
            _logger.error("AfterShip webhook registration failed [%s]: %s", r.status_code, r.text)
            r.raise_for_status()
        
        return r.json()
    
    def list_webhooks(self):
        """
        Lấy danh sách các webhook đã đăng ký
        
        Returns:
            dict: Danh sách webhooks
        """
        url = f"{AFTERSHIP_API_BASE}/webhooks"
        r = requests.get(url, headers=self.headers, timeout=20)
        r.raise_for_status()
        return r.json()
    
    def delete_webhook(self, webhook_id: str):
        """
        Xóa webhook đã đăng ký
        
        Args:
            webhook_id: ID của webhook cần xóa
        
        Returns:
            dict: Response từ AfterShip API
        """
        url = f"{AFTERSHIP_API_BASE}/webhooks/{webhook_id}"
        r = requests.delete(url, headers=self.headers, timeout=20)
        r.raise_for_status()
        return r.json()
