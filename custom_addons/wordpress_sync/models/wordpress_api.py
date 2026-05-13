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
BATCH_SIZE_LIMIT = 100


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

    def get_all_products_map(self):
        """
        Lấy tất cả sản phẩm từ WooCommerce để tạo map SKU -> ID
        
        Returns:
            dict: {sku: {'id': id, 'type': type, 'parent_id': parent_id}}
        """
        product_map = {}
        page = 1
        
        while True:
            # Chỉ lấy các field cần thiết để tối ưu
            url = f"{self.base_url}/products?page={page}&per_page=100&fields=id,sku,type,parent_id"
            products = self._get(url)
            
            if not products:
                break
                
            for p in products:
                if p.get('sku'):
                    product_map[p['sku']] = {
                        'id': p['id'],
                        'type': p.get('type', 'simple'),
                        'parent_id': p.get('parent_id', 0)
                    }
            
            page += 1
            # Simple rate limiting check inside loop if needed, 
            # though paginated GET is usually safe.
            
        return product_map

    def update_products_batch(self, update_data):
        """
        Cập nhật hàng loạt sản phẩm (Batch API)
        
        Args:
            update_data: List các dict update item
            
        Returns:
            dict: Response data
        """
        # Batch API expects: { 'update': [ { 'id': 123, ... }, ... ] }
        payload = {'update': update_data}
        return self._post("/products/batch", payload)

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
        # Priority: Manual price > Computed combo price
        regular_price = getattr(product, 'x_studio_ga_hng_nim_yt', 0.0) or 0.0
        sale_price = getattr(product, 'x_studio_ga_web', 0.0) or 0.0
        
        # Check for BOM (combo product) - only use computed price if NO manual price
        has_bom = self.env['mrp.bom'].search_count([
            ('product_tmpl_id', '=', product.id),
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ]) > 0
        
        if has_bom and sale_price <= 0:
            # No manual sale price -> use computed combo price
            combo_price = product.computed_combo_selling_price
            if combo_price > 0:
                sale_price = combo_price
                # If no regular price either, use combo price
                if regular_price <= 0:
                    regular_price = combo_price

        result['regular_price'] = regular_price
        result['sale_price'] = sale_price

        # Validate regular price
        if regular_price < 0:
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

    def sync_products_batch(self, products, product_map=None):
        """
        Đồng bộ danh sách sản phẩm theo batch
        """
        # 1. Prepare map if not provided
        if product_map is None:
            _logger.info("Fetching all products from WooCommerce to build map...")
            product_map = self.api.get_all_products_map()
            _logger.info(f"Fetched {len(product_map)} products from WooCommerce")
            
        batch_data = []
        product_by_sku = {}
        
        results = {} # {product_id: result_dict}

        # 2. Build batch payload
        for product in products:
            sku = product.default_code
            if not sku:
                results[product.id] = {
                    'success': False, 
                    'message': 'Không có SKU',
                    'sku': '',
                    'wc_product_id': ''
                }
                continue
                
            wc_info = product_map.get(sku)
            if not wc_info:
                results[product.id] = {
                    'success': False, 
                    'message': f'Không tìm thấy SKU {sku} trên WordPress',
                    'sku': sku,
                    'wc_product_id': ''
                }
                continue
                
            # Get prices
            regular_price = getattr(product, 'x_studio_ga_hng_nim_yt', 0.0) or 0.0
            sale_price = getattr(product, 'x_studio_ga_web', 0.0) or 0.0
            
            # Prepare item payload
            item_data = {
                'id': wc_info['id'],
                'regular_price': str(regular_price)
            }
            
            if sale_price > 0 and sale_price < regular_price:
                item_data['sale_price'] = str(sale_price)
            else:
                item_data['sale_price'] = ''
                
            batch_data.append(item_data)
            product_by_sku[sku] = product
            
            # Init result entry
            results[product.id] = {
                'success': False, # Will update later
                'message': 'Lỗi không xác định',
                'sku': sku,
                'wc_product_id': str(wc_info['id']),
                'regular_price': regular_price,
                'sale_price': sale_price
            }

        # 3. Send Batch Request if data exists
        if batch_data:
            response = self.api.update_products_batch(batch_data)
            
            if response and 'update' in response:
                # Parse response for individual status
                # Batch API returns list of updated objects or errors
                # But typically returns the updated objects in 'update' list
                # We need to map back to our products. 
                # The response objects contain 'id' and 'sku'
                
                updated_items = {str(item.get('id')): item for item in response['update']}
                
                for product in products:
                    if product.id in results and results[product.id]['wc_product_id']:
                        wc_id = results[product.id]['wc_product_id']
                        
                        if wc_id in updated_items:
                            # Check if item itself has error (rare in successful batch 200)
                            # Or if it's just the updated object
                            item_resp = updated_items[wc_id]
                            if 'error' in item_resp:
                                results[product.id]['success'] = False
                                results[product.id]['message'] = str(item_resp['error'])
                            else:
                                results[product.id]['success'] = True
                                results[product.id]['message'] = 'Cập nhật thành công (Batch)'
                                # Purge cache (optional, might spam if done here. 
                                # Better to use bulk purge if available or skip for speed)
                        else:
                            # Item in payload but not in response?
                            # Could be an error that caused it to be dropped
                            pass
            else:
                # Whole batch failed
                error_msg = 'Batch request failed'
                for pid in results:
                    if results[pid]['wc_product_id']: 
                        results[pid]['message'] = error_msg

        return results


# ===========================================
# STOCK SYNC SERVICE
# ===========================================
class StockSyncService:
    """
    Service xử lý logic đồng bộ tình trạng kho

    Usage:
        service = StockSyncService(env, config)
        result = service.sync_stock_status(product)
    """

    # Stock status mapping
    STOCK_STATUS_MAP = {
        'in_stock': 'instock',
        'out_of_stock': 'outofstock'
    }

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

    def _get_stock_field(self):
        """Get configured stock field name from wordpress.config"""
        return self.config.stock_status_field or 'qty_available'

    def _is_in_stock(self, product):
        """
        Kiểm tra sản phẩm còn hàng không dựa trên field được cấu hình
        Priority: Manual Override (x_wp_stock_status) > Computed Qty
        """
        # 0. Invalidate cache to ensure fresh data from DB (in case of race/cache issues)
        product.invalidate_recordset(['x_wp_stock_status'])

        # 1. Manual Override
        manual_status = getattr(product, 'x_wp_stock_status', False)
        
        _logger.info(f"[WP-STOCK-DEBUG] {product.name} (ID: {product.id}) | Manual Override: '{manual_status}'")

        if manual_status:
            if manual_status == 'instock':
                _logger.info(f"[WP-STOCK-DEBUG] {product.name} -> RETURNING INSTOCK (Manual)")
                return True
            if manual_status in ('outofstock', 'discontinued'):
                _logger.info(f"[WP-STOCK-DEBUG] {product.name} -> RETURNING OUTOFSTOCK (Manual)")
                return False

        # 2. Check Phantom BOM (Recursive)
        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', product.id),
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ], limit=1)
        
        if bom:
            # If ANY component is OOS, the Kit is OOS
            for line in bom.bom_line_ids:
                child = line.product_id.product_tmpl_id
                if not self._is_in_stock(child):
                    _logger.info(f"Checking stock for {product.name}: Component {child.name} is OOS. Kit is OOS.")
                    return False
            # All components in stock -> Kit is in stock
            _logger.info(f"Checking stock for {product.name}: All components in stock. Kit is In Stock.")
            return True

        # 3. Check Configuration: Sync based on Qty?
        if not self.config.sync_stock_based_on_quantity:
            # If Config says "Don't sync based on quantity" -> We assume In Stock (unless Manual Override was OOS)
            _logger.info(f"Checking stock for {product.name}: Sync based on Qty is OFF -> Returning In Stock.")
            return True

        # 4. Computed from Quantity (Standard)
        stock_field = self._get_stock_field()

        # For product.template, we need to check all variants
        # Get total qty from all product variants
        total_qty = 0
        for variant in product.product_variant_ids:
            qty = getattr(variant, stock_field, 0) or 0
            total_qty += qty

        return total_qty > 0

    def sync_stock_status(self, product):
        """
        Đồng bộ tình trạng kho một product lên WordPress

        Args:
            product: product.template record

        Returns:
            dict: {
                'success': bool,
                'message': str,
                'wc_product_id': str,
                'stock_status': str
            }
        """
        sku = product.default_code or ''
        result = {
            'success': False,
            'message': '',
            'wc_product_id': '',
            'sku': sku,
            'stock_status': ''
        }

        # Validate SKU
        if not sku:
            result['message'] = 'Product không có SKU'
            return result

        # Get stock status
        is_in_stock = self._is_in_stock(product)
        stock_status = self.STOCK_STATUS_MAP['in_stock'] if is_in_stock else self.STOCK_STATUS_MAP['out_of_stock']
        result['stock_status'] = stock_status

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

        # Prepare stock payload
        payload = {'stock_status': stock_status}

        # Update product on WordPress
        response = self.api.update_product(
            wc_id,
            payload,
            is_variation=is_variation,
            parent_id=parent_id
        )

        if response:
            result['success'] = True
            status_text = 'Còn hàng' if is_in_stock else 'Hết hàng'
            result['message'] = f'Stock status: {status_text} → {stock_status}'

            # Purge cache
            self.api.purge_cache(self.config.cache_purge_url, sku)

            _logger.info(f"Synced stock status for {product.name} (SKU: {sku}) → {stock_status}")
        else:
            result['message'] = 'Không thể cập nhật stock status lên WordPress'

        return result

    def sync_products_stock_batch(self, products, product_map=None):
        """
        Đồng bộ stock status danh sách sản phẩm theo batch
        """
        # 1. Prepare map if not provided
        if product_map is None:
            _logger.info("Fetching all products from WooCommerce to build map...")
            product_map = self.api.get_all_products_map()
            _logger.info(f"Fetched {len(product_map)} products from WooCommerce")

        batch_data = []
        results = {}  # {product_id: result_dict}

        # 2. Build batch payload
        for product in products:
            sku = product.default_code
            if not sku:
                results[product.id] = {
                    'success': False,
                    'message': 'Không có SKU',
                    'sku': '',
                    'wc_product_id': '',
                    'stock_status': ''
                }
                continue

            wc_info = product_map.get(sku)
            if not wc_info:
                results[product.id] = {
                    'success': False,
                    'message': f'Không tìm thấy SKU {sku} trên WordPress',
                    'sku': sku,
                    'wc_product_id': '',
                    'stock_status': ''
                }
                continue

            # Get stock status
            is_in_stock = self._is_in_stock(product)
            stock_status = self.STOCK_STATUS_MAP['in_stock'] if is_in_stock else self.STOCK_STATUS_MAP['out_of_stock']

            # Prepare item payload
            item_data = {
                'id': wc_info['id'],
                'stock_status': stock_status
            }

            batch_data.append(item_data)

            # Init result entry
            results[product.id] = {
                'success': False,  # Will update later
                'message': 'Lỗi không xác định',
                'sku': sku,
                'wc_product_id': str(wc_info['id']),
                'stock_status': stock_status
            }

        # 3. Send Batch Request if data exists
        if batch_data:
            response = self.api.update_products_batch(batch_data)

            if response and 'update' in response:
                updated_items = {str(item.get('id')): item for item in response['update']}

                for product in products:
                    if product.id in results and results[product.id]['wc_product_id']:
                        wc_id = results[product.id]['wc_product_id']

                        if wc_id in updated_items:
                            item_resp = updated_items[wc_id]
                            if 'error' in item_resp:
                                results[product.id]['success'] = False
                                results[product.id]['message'] = str(item_resp['error'])
                            else:
                                results[product.id]['success'] = True
                                results[product.id]['message'] = 'Cập nhật stock thành công (Batch)'
            else:
                error_msg = 'Batch request failed'
                for pid in results:
                    if results[pid]['wc_product_id']:
                        results[pid]['message'] = error_msg

        return results

