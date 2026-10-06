# -*- coding: utf-8 -*-
"""
WooCommerce API Client
Tập trung tất cả lời gọi WooCommerce REST API. Logic đồng bộ nằm ở wordpress_sync_service.
"""
import requests
from requests.auth import HTTPBasicAuth
import logging
import time
from urllib.parse import quote

from .wordpress_sync_utils import catalogue_entry, should_track

_logger = logging.getLogger(__name__)

# Constants
DEFAULT_TIMEOUT = 10
LIST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds
BATCH_SIZE_LIMIT = 100

# Chỉ xin đúng các field cần cho bảng liên kết; không có _fields thì mỗi sản phẩm kéo về
# cả mô tả, ảnh, meta — chậm hơn nhiều lần.
CATALOGUE_FIELDS = 'id,sku,name,type,status,parent_id,permalink'
VARIATION_FIELDS = 'id,sku,name,status,permalink'


class WooCommerceAPIError(Exception):
    """Lỗi gọi API mà bên gọi phải dừng lại, không được coi như kết quả rỗng."""


class WooCommerceAPI:
    """
    WooCommerce REST API Client

    Usage:
        api = WooCommerceAPI(domain, consumer_key, consumer_secret)
        product = api.find_product_by_sku('SKU123')
        api.update_product(product_id, {'regular_price': '100000'})
    """

    def __init__(self, domain, consumer_key, consumer_secret):
        """
        Initialize API client

        Args:
            domain: WordPress domain (e.g., https://hoanglongvu.com)
            consumer_key: WooCommerce Consumer Key
            consumer_secret: WooCommerce Consumer Secret
        """
        self.domain = domain.rstrip('/')
        self.base_url = f"{self.domain}/wp-json/wc/v3"
        self.auth = HTTPBasicAuth(consumer_key, consumer_secret)

    # ===========================================
    # PRODUCT METHODS
    # ===========================================
    def find_product_by_sku(self, sku):
        """
        Tìm product trên WooCommerce theo SKU

        Args:
            sku: Product SKU

        Returns:
            dict: Product data nếu tìm thấy, None nếu không
        """
        try:
            # SKU phải mã hoá: ghép thẳng vào URL thì '+' bị server đọc thành dấu cách
            # (combo 'A+B+C' thành 'A B C') → không tìm thấy sản phẩm.
            response = self._get(f"{self.base_url}/products", params={'sku': sku, 'per_page': 100})

            if response and len(response) > 0:
                return response[0]
            return None

        except Exception as e:
            _logger.error(f"Error finding product by SKU {sku}: {e}")
            return None

    def update_product(self, product_id, data, is_variation=False, parent_id=None):
        """
        Cập nhật product trên WooCommerce

        Args:
            product_id: WooCommerce product ID
            data: Dict data cần update (e.g., {'regular_price': '100000'})
            is_variation: True nếu là variation
            parent_id: Parent product ID nếu là variation

        Returns:
            dict: Response data nếu thành công, None nếu thất bại
        """
        if is_variation and parent_id:
            path = f"/products/{parent_id}/variations/{product_id}"
        else:
            path = f"/products/{product_id}"

        return self._put(path, data)

    def fetch_catalogue(self):
        """
        Lấy toàn bộ sản phẩm trên web, gồm cả biến thể.

        /products không trả biến thể, nên mỗi sản phẩm 'variable' phải hỏi thêm
        /products/<id>/variations.

        Returns:
            list dict theo catalogue_entry, đã bỏ vỏ variable không SKU.

        Raises:
            WooCommerceAPIError nếu một trang lỗi — trả danh sách thiếu sẽ khiến bên gọi
            tưởng các sản phẩm còn lại đã bị xoá khỏi web.
        """
        entries = []
        for raw in self._get_all_pages('/products', {'_fields': CATALOGUE_FIELDS}):
            entry = catalogue_entry(raw)
            if should_track(entry):
                entries.append(entry)
            if entry['wc_type'] == 'variable':
                entries.extend(self.fetch_variations(entry['wc_product_id'], entry['wc_name']))
        return entries

    def fetch_variations(self, parent_id, parent_name=''):
        """
        Lấy mọi biến thể của một sản phẩm variable.

        Returns:
            list dict theo catalogue_entry. Raises WooCommerceAPIError nếu lỗi.
        """
        raws = self._get_all_pages(f'/products/{parent_id}/variations', {'_fields': VARIATION_FIELDS})
        return [catalogue_entry(raw, parent_id=parent_id, fallback_name=parent_name) for raw in raws]

    def update_products_batch(self, update_data):
        """
        Cập nhật hàng loạt sản phẩm thường (không dùng cho biến thể).

        Args:
            update_data: List dict, mỗi dict có 'id' và các field cần đổi

        Returns:
            dict: Response data, None nếu lỗi
        """
        return self._post("/products/batch", {'update': update_data})

    def update_variations_batch(self, parent_id, update_data):
        """
        Cập nhật hàng loạt biến thể của một sản phẩm cha.

        /products/batch không nhận ID biến thể, nên biến thể phải đi endpoint này.

        Returns:
            dict: Response data, None nếu lỗi
        """
        return self._post(f"/products/{parent_id}/variations/batch", {'update': update_data})

    # ===========================================
    # CACHE METHODS
    # ===========================================
    def purge_cache(self, cache_url, sku):
        """
        Purge LiteSpeed cache cho product

        Args:
            cache_url: Cache purge URL path
            sku: Product SKU
        """
        if not cache_url:
            return

        try:
            url = f"{self.domain}{cache_url}{quote(sku, safe='')}"
            requests.get(url, timeout=5)
            _logger.info(f"Cache purged for SKU: {sku}")
        except Exception as e:
            _logger.warning(f"Cache purge failed for {sku}: {e}")

    # ===========================================
    # HTTP METHODS
    # ===========================================
    def _get_all_pages(self, path, params=None):
        """
        GET lần lượt mọi trang của một collection.

        Returns:
            list: gộp item của mọi trang. Raises WooCommerceAPIError nếu một trang lỗi.
        """
        items = []
        page = 1
        while True:
            page_params = dict(params or {}, per_page=BATCH_SIZE_LIMIT, page=page)
            batch = self._get(f"{self.base_url}{path}", params=page_params, timeout=LIST_TIMEOUT)
            if batch is None:
                raise WooCommerceAPIError(f"GET {path} trang {page} lỗi")
            items.extend(batch)
            if len(batch) < BATCH_SIZE_LIMIT:
                return items
            page += 1

    def _get(self, url, params=None, timeout=DEFAULT_TIMEOUT):
        """
        GET request

        Args:
            url: Full URL to request
            params: Dict query string, requests tự mã hoá giá trị
            timeout: Request timeout in seconds

        Returns:
            dict/list: Response JSON data, None nếu lỗi
        """
        try:
            response = requests.get(url, params=params, auth=self.auth, timeout=timeout)

            if response.status_code == 200:
                return response.json()
            else:
                _logger.error(f"GET {url} failed: HTTP {response.status_code}")
                return None

        except requests.exceptions.Timeout:
            _logger.error(f"GET {url} timeout")
            return None
        except requests.exceptions.ConnectionError:
            _logger.error(f"GET {url} connection error")
            return None
        except Exception as e:
            _logger.error(f"GET {url} error: {e}")
            return None

    def _put(self, path, data, retries=MAX_RETRIES):
        """
        PUT request với retry logic

        Args:
            path: API path (e.g., /products/123)
            data: Dict data để gửi
            retries: Số lần retry tối đa

        Returns:
            dict: Response JSON data nếu thành công, None nếu thất bại
        """
        url = f"{self.base_url}{path}"

        for attempt in range(retries):
            try:
                response = requests.put(
                    url,
                    json=data,
                    auth=self.auth,
                    timeout=DEFAULT_TIMEOUT
                )

                if response.status_code in (200, 201):
                    return response.json()

                error_msg = f"HTTP {response.status_code}: {response.text[:100]}"
                _logger.warning(f"PUT {path} attempt {attempt + 1}/{retries}: {error_msg}")

                if attempt < retries - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))

            except requests.exceptions.Timeout:
                _logger.warning(f"PUT {path} attempt {attempt + 1}/{retries}: timeout")
                if attempt < retries - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
            except Exception as e:
                _logger.warning(f"PUT {path} attempt {attempt + 1}/{retries}: {e}")
                if attempt < retries - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))

        _logger.error(f"PUT {path} failed after {retries} attempts")
        return None

    def _post(self, path, data, retries=MAX_RETRIES):
        """
        POST request (cho Batch API)
        """
        url = f"{self.base_url}{path}"

        for attempt in range(retries):
            try:
                response = requests.post(
                    url,
                    json=data,
                    auth=self.auth,
                    timeout=30 # Batch requests might take longer
                )

                if response.status_code in (200, 201):
                    return response.json()

                _logger.warning(f"POST {path} attempt {attempt+1}: {response.status_code}")
                if attempt < retries - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
            except Exception as e:
                _logger.error(f"POST {path} error: {e}")
                if attempt < retries - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))

        return None
