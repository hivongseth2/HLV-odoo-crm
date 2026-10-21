# -*- coding: utf-8 -*-
"""
Cloudflare API client — chỉ dùng để xoá cache trang trên CDN sau khi đổi giá/tồn kho.

Web cache trang HTML ở Cloudflare (Edge TTL vài giờ), nên đẩy giá xong mà không xoá thì
khách vẫn thấy giá cũ tới khi cache hết hạn.
"""
import logging

import requests

from .wordpress_sync_utils import chunked

_logger = logging.getLogger(__name__)

API_BASE = 'https://api.cloudflare.com/client/v4'
# Gói Free/Pro/Business nhận tối đa 30 URL mỗi lần gọi purge theo URL.
PURGE_URL_LIMIT = 30
TIMEOUT = 10


class CloudflareAPI:
    """
    Usage:
        errors = CloudflareAPI(zone_id, api_token).purge_urls(['https://site/san-pham/a/'])
    """

    def __init__(self, zone_id, api_token):
        self.zone_id = zone_id
        self.api_token = api_token

    def purge_urls(self, urls):
        """
        Xoá cache các URL trên Cloudflare, chia lượt theo PURGE_URL_LIMIT.

        Returns:
            list: chuỗi lỗi của các lượt thất bại; rỗng nghĩa là xoá hết (hoặc không có URL).
        """
        errors = []
        for chunk in chunked(list(urls), PURGE_URL_LIMIT):
            try:
                response = requests.post(
                    f'{API_BASE}/zones/{self.zone_id}/purge_cache',
                    json={'files': chunk},
                    headers={'Authorization': f'Bearer {self.api_token}'},
                    timeout=TIMEOUT,
                )
                if response.status_code == 200 and response.json().get('success'):
                    continue
                errors.append(f'HTTP {response.status_code}: {response.text[:200]}')
            except (requests.exceptions.RequestException, ValueError) as e:
                errors.append(str(e))
        return errors
