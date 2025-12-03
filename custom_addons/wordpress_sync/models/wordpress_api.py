# -*- coding: utf-8 -*-
"""
WooCommerce API Service
Tập trung tất cả logic gọi WooCommerce REST API.
"""
import requests
from requests.auth import HTTPBasicAuth
import logging
import time

_logger = logging.getLogger(__name__)

# Constants
DEFAULT_TIMEOUT = 10
MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds


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
            url = f"{self.base_url}/products?sku={sku}&per_page=100"
            response = self._get(url)

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
            url = f"{self.domain}{cache_url}{sku}"
            requests.get(url, timeout=5)
            _logger.info(f"Cache purged for SKU: {sku}")
        except Exception as e:
            _logger.warning(f"Cache purge failed for {sku}: {e}")

    # ===========================================
    # HTTP METHODS
    # ===========================================
    def _get(self, url, timeout=DEFAULT_TIMEOUT):
        """
        GET request

        Args:
            url: Full URL to request
            timeout: Request timeout in seconds

        Returns:
            dict/list: Response JSON data, None nếu lỗi
        """
        try:
            response = requests.get(url, auth=self.auth, timeout=timeout)

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


# ===========================================
# SYNC SERVICE
# ===========================================
class PriceSyncService:
    """
    Service xử lý logic đồng bộ giá

    Usage:
        service = PriceSyncService(env, config)
        result = service.sync_product(product)
    """

    def __init__(self, env, config):
        """
        Initialize service

        Args:
            env: Odoo environment
            config: wordpress.config record
        """
        self.env = env
        self.config = config

        # Initialize API client
        wc_key, wc_secret = config.get_credentials()
        self.api = WooCommerceAPI(config.wc_domain, wc_key, wc_secret)

    def sync_product(self, product):
        """
        Đồng bộ giá một product lên WordPress

        Args:
            product: product.template record

        Returns:
            dict: {
                'success': bool,
                'message': str,
                'wc_product_id': str,
                'regular_price': float,
                'sale_price': float
            }
        """
        sku = product.default_code or ''
        result = {
            'success': False,
            'message': '',
            'wc_product_id': '',
            'sku': sku,
            'regular_price': 0,
            'sale_price': 0
        }

        # Validate SKU
        if not sku:
            result['message'] = 'Product không có SKU'
            return result

        # Get prices from Odoo
        regular_price = getattr(product, 'x_studio_ga_web', 0.0) or 0.0
        sale_price = getattr(product, 'x_studio_gi_bn_thng_mi', 0.0) or 0.0

        result['regular_price'] = regular_price
        result['sale_price'] = sale_price

        # Validate regular price
        if regular_price <= 0:
            result['message'] = f'Giá regular không hợp lệ: {regular_price}'
            return result

        # Find product on WordPress
        wc_product = self.api.find_product_by_sku(sku)
        if not wc_product:
            result['message'] = f'Không tìm thấy product trên WordPress (SKU: {sku})'
            return result

        # Extract WC product info
        wc_id = wc_product.get('id')
        is_variation = wc_product.get('type') == 'variation'
        parent_id = wc_product.get('parent_id', 0) if is_variation else None

        result['wc_product_id'] = str(wc_id)

        # Prepare price payload
        payload = {'regular_price': str(regular_price)}

        # Sale price: phải > 0 và < regular_price
        has_valid_sale = sale_price > 0 and sale_price < regular_price
        if has_valid_sale:
            payload['sale_price'] = str(sale_price)
        else:
            payload['sale_price'] = ''  # Clear sale price on WordPress

        # Update product on WordPress
        response = self.api.update_product(
            wc_id,
            payload,
            is_variation=is_variation,
            parent_id=parent_id
        )

        if response:
            result['success'] = True
            result['message'] = f'Regular: {regular_price:,.0f}, Sale: {sale_price:,.0f}' if has_valid_sale else f'Regular: {regular_price:,.0f}'

            # Purge cache
            self.api.purge_cache(self.config.cache_purge_url, sku)

            _logger.info(f"Synced {product.name} (SKU: {sku}) to WordPress")
        else:
            result['message'] = 'Không thể cập nhật lên WordPress'

        return result
