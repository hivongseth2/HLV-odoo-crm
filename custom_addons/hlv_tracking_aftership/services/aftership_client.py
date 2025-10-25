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