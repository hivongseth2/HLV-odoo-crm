import requests
import logging

_logger = logging.getLogger(__name__)

AFTERSHIP_API_BASE = "https://api.aftership.com/tracking/2025-07"

class AfterShipClient:
    """
    Lightweight client for AfterShip v2024-04 Tracking API.
    Docs: https://docs.aftership.com
    """
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("AfterShip API key is required")
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
            "as-api-key": api_key, 
        }

    def create_tracking(self, slug: str, tracking_number: str, title: str = None):
        payload = {
        "tracking_number": tracking_number,
        "slug": slug
             }

        url = f"{AFTERSHIP_API_BASE}/trackings"
        r = requests.post(url, json=payload, headers=self.headers, timeout=20)
        r.raise_for_status()
        return r.json()

    def get_tracking_by_id(self, tracking_id: str):
        url = f"{AFTERSHIP_API_BASE}/trackings/{tracking_id}"
        r = requests.get(url, headers=self.headers, timeout=20)
        r.raise_for_status()
        return r.json()

    def get_tracking_by_number(self, slug: str, tracking_number: str):
        url = f"{AFTERSHIP_API_BASE}/trackings/{slug}/{tracking_number}"
        r = requests.get(url, headers=self.headers, timeout=20)
        r.raise_for_status()
        return r.json()